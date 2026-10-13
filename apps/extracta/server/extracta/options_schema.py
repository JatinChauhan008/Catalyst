"""Describe Docling option models for a generic form, and rebuild them from form input.

The frontend does not hard-code any Docling option. It receives a tree of
`FieldSpec` items that this module derives from the Pydantic option models
(`PdfPipelineOptions`, `HTMLBackendOptions`, OCR engine options, ...). A new
option in Docling therefore appears in the UI without code changes.

Polymorphic fields are "variants": a field typed `OcrOptions` can hold any
registered OCR engine options class, and the UI offers a choice between them.
Some option classes also have named presets (VLM models, ASR models).

Form input is sparse. For each model the client sends only the fields that
the user changed:

    {"do_ocr": true, "ocr_options": {"__variant__": "SarvamOcrOptions", "lang": ["hi-IN"]}}

`apply_overrides` starts from a default instance and applies these changes, so
defaults that cannot be serialized (secrets, callables) stay intact.
"""

from __future__ import annotations

import enum
import inspect
import logging
import types
from collections.abc import Callable
from functools import lru_cache
from pathlib import PurePath
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError

from docling.datamodel.pipeline_options import (
    BaseLayoutOptions,
    BaseTableStructureOptions,
    OcrOptions,
    PictureDescriptionBaseOptions,
)
from docling.models.factories import (
    get_layout_factory,
    get_ocr_factory,
    get_picture_description_factory,
    get_table_structure_factory,
)

_log = logging.getLogger(__name__)

VARIANT_KEY = "__variant__"
PRESET_KEY = "__preset__"
MAX_DEPTH = 8

FieldKind = Literal[
    "bool", "int", "float", "string", "secret", "enum", "list", "object", "variant", "json"
]  # fmt: skip


class PresetSpec(BaseModel):
    id: str
    label: str
    description: str | None = None
    variant: str
    values: dict[str, Any]


class VariantSpec(BaseModel):
    id: str
    label: str
    description: str | None = None
    fields: list[FieldSpec]


class FieldSpec(BaseModel):
    name: str
    title: str
    description: str | None = None
    kind: FieldKind
    nullable: bool = False
    default: Any = None
    has_default: bool = True
    default_is_null: bool = False
    unserializable_default: bool = False
    enum: list[Any] | None = None
    item_kind: FieldKind | None = None
    item_enum: list[Any] | None = None
    constraints: dict[str, float] = {}
    examples: list[Any] | None = None
    fields: list[FieldSpec] | None = None
    variants: list[VariantSpec] | None = None
    default_variant: str | None = None
    presets: list[PresetSpec] | None = None


VariantSpec.model_rebuild()


# --------------------------------------------------------------------- registry
_FACTORY_BASES: list[tuple[type[BaseModel], Callable[..., Any]]] = [
    (OcrOptions, get_ocr_factory),
    (BaseLayoutOptions, get_layout_factory),
    (BaseTableStructureOptions, get_table_structure_factory),
    (PictureDescriptionBaseOptions, get_picture_description_factory),
]


class _Registry:
    """Maps variant and preset ids to classes and instances."""

    def __init__(self) -> None:
        self.variants: dict[str, type[BaseModel]] = {}
        self.presets: dict[str, Callable[[], BaseModel]] = {}

    def variant_id(self, cls: type[BaseModel]) -> str:
        variant_id = cls.__name__
        known = self.variants.get(variant_id)
        if known is not None and known is not cls:
            variant_id = f"{cls.__module__}.{cls.__qualname__}"
        self.variants[variant_id] = cls
        return variant_id


_registry = _Registry()
_preset_providers: list[
    Callable[
        [type[BaseModel]], list[tuple[str, str, str | None, Callable[[], BaseModel]]]
    ]
] = []


def register_preset_provider(
    provider: Callable[
        [type[BaseModel]], list[tuple[str, str, str | None, Callable[[], BaseModel]]]
    ],
) -> None:
    """Add a function that lists presets (id, label, description, factory) for a base class."""
    _preset_providers.append(provider)


def _all_subclasses(cls: type) -> list[type]:
    found: list[type] = []
    stack = [cls]
    while stack:
        current = stack.pop()
        for sub in current.__subclasses__():
            if sub not in found:
                found.append(sub)
                stack.append(sub)
    return found


def _concrete_variants(bases: list[type[BaseModel]]) -> list[type[BaseModel]]:
    """The instantiable option classes a field typed with `bases` can hold."""
    candidates: list[type[BaseModel]] = []
    for base in bases:
        for cls in [base, *_all_subclasses(base)]:
            if cls not in candidates:
                candidates.append(cls)

    result: list[type[BaseModel]] = []
    for cls in candidates:
        if inspect.isabstract(cls) or cls.__name__.startswith("_"):
            continue
        if cls.__module__.startswith(("tests.", "test_")):
            continue
        factory_classes = _factory_classes_for(cls)
        if factory_classes is not None and cls not in factory_classes:
            continue
        result.append(cls)
    return result


def _factory_classes_for(cls: type) -> set[type] | None:
    for base, factory_getter in _FACTORY_BASES:
        if issubclass(cls, base):
            return set(factory_getter(allow_external_plugins=True).classes.keys())
    return None


def _presets_for(
    bases: list[type[BaseModel]],
) -> list[tuple[str, str, str | None, Callable[[], BaseModel]]]:
    presets = []
    for base in bases:
        for provider in _preset_providers:
            presets.extend(provider(base))
    return presets


# ---------------------------------------------------------------- type helpers
def _unwrap(annotation: Any) -> tuple[Any, bool]:
    """Strip `Annotated` and `None` from a type. Return (core type, nullable)."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _unwrap(get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        args = get_args(annotation)
        non_none = [arg for arg in args if arg is not type(None)]
        nullable = len(non_none) < len(args)
        if len(non_none) == 1:
            core, inner_nullable = _unwrap(non_none[0])
            return core, nullable or inner_nullable
        return Union[tuple(non_none)], nullable
    return annotation, False


def _union_members(core: Any) -> list[Any]:
    if get_origin(core) in (Union, types.UnionType):
        return [_unwrap(arg)[0] for arg in get_args(core)]
    return [core]


def _is_model(tp: Any) -> bool:
    return inspect.isclass(tp) and issubclass(tp, BaseModel)


def _scalar_kind(tp: Any) -> tuple[FieldKind, list[Any] | None] | None:
    if tp is bool:
        return "bool", None
    if tp is int:
        return "int", None
    if tp is float:
        return "float", None
    if tp is str:
        return "string", None
    if inspect.isclass(tp) and issubclass(tp, SecretStr):
        return "secret", None
    if inspect.isclass(tp) and issubclass(tp, PurePath):
        return "string", None
    if inspect.isclass(tp) and issubclass(tp, enum.Enum):
        return "enum", [member.value for member in tp]
    if get_origin(tp) is Literal:
        return "enum", list(get_args(tp))
    members = _union_members(tp)
    if len(members) > 1:
        kinds = [_scalar_kind(member) for member in members]
        if all(kind is not None for kind in kinds):
            names = {kind[0] for kind in kinds if kind is not None}
            if names <= {"int", "float"}:
                return "float", None
            if "string" in names:
                return "string", None
    return None


def _json_default(annotation: Any, value: Any) -> tuple[Any, bool]:
    """JSON form of a default value. Returns (value, unserializable)."""
    if value is None:
        return None, False
    if isinstance(value, SecretStr):
        return None, False
    try:
        return TypeAdapter(annotation).dump_python(value, mode="json"), False
    except Exception:
        try:
            return TypeAdapter(Any).dump_python(value, mode="json"), False
        except Exception:
            return None, True


def _constraints(field_info: Any) -> dict[str, float]:
    found: dict[str, float] = {}
    for item in field_info.metadata:
        for name in ("ge", "le", "gt", "lt", "min_length", "max_length"):
            value = getattr(item, name, None)
            if isinstance(value, int | float) and not isinstance(value, bool):
                found[name] = value
    return found


def _first_doc_line(cls: type) -> str | None:
    doc = inspect.getdoc(cls)
    if not doc or cls.__doc__ is None:
        return None
    return doc.strip().split("\n\n")[0].replace("\n", " ")


# ----------------------------------------------------------------- description
def describe_model(model: BaseModel, depth: int = 0) -> list[FieldSpec]:
    """Describe every public field of an option model instance."""
    cls = type(model)
    specs = []
    for name, field_info in cls.model_fields.items():
        if name.startswith("_") or field_info.exclude:
            continue
        value = getattr(model, name, None)
        specs.append(_describe_field(name, field_info, value, depth))
    return specs


def describe_model_class(cls: type[BaseModel], depth: int = 0) -> list[FieldSpec]:
    """Describe a model class. Uses a default instance when one can be built."""
    instance = _try_instantiate(cls)
    if instance is not None:
        return describe_model(instance, depth)
    specs = []
    for name, field_info in cls.model_fields.items():
        if name.startswith("_") or field_info.exclude:
            continue
        default = (
            None
            if field_info.is_required()
            else field_info.get_default(call_default_factory=True)
        )
        spec = _describe_field(name, field_info, default, depth)
        spec.has_default = not field_info.is_required()
        specs.append(spec)
    return specs


def _try_instantiate(cls: type[BaseModel]) -> BaseModel | None:
    try:
        return cls()
    except Exception:
        return None


def _describe_field(name: str, field_info: Any, value: Any, depth: int) -> FieldSpec:
    annotation = field_info.annotation
    core, nullable = _unwrap(annotation)
    spec = FieldSpec(
        name=name,
        title=field_info.title or name.replace("_", " ").capitalize(),
        description=field_info.description,
        kind="json",
        nullable=nullable,
        constraints=_constraints(field_info),
    )
    if field_info.examples:
        spec.examples, _ = _json_default(Any, field_info.examples)

    scalar = _scalar_kind(core)
    if scalar is not None:
        spec.kind, spec.enum = scalar
        spec.default, spec.unserializable_default = _json_default(annotation, value)
        return spec

    origin = get_origin(core)
    if origin in (list, tuple, set, frozenset):
        args = [arg for arg in get_args(core) if arg is not Ellipsis]
        item = _scalar_kind(_unwrap(args[0])[0]) if len(args) == 1 else None
        if item is not None:
            spec.kind = "list"
            spec.item_kind, spec.item_enum = item
        spec.default, spec.unserializable_default = _json_default(annotation, value)
        return spec

    members = _union_members(core)
    if depth < MAX_DEPTH and members and all(_is_model(member) for member in members):
        spec.default_is_null = value is None
        variants = _concrete_variants(members)
        presets = _presets_for(variants)
        if len(variants) > 1 or presets:
            spec.kind = "variant"
            spec.variants = [_describe_variant(cls, value, depth) for cls in variants]
            if isinstance(value, BaseModel):
                spec.default_variant = _registry.variant_id(type(value))
            described = [_describe_preset(*preset, depth=depth) for preset in presets]
            spec.presets = [
                preset for preset in described if preset is not None
            ] or None
            return spec
        if len(variants) == 1:
            spec.kind = "object"
            model_cls = variants[0]
            spec.fields = (
                describe_model(value, depth + 1)
                if isinstance(value, model_cls)
                else describe_model_class(model_cls, depth + 1)
            )
            return spec

    spec.default, spec.unserializable_default = _json_default(annotation, value)
    return spec


def _describe_variant(cls: type[BaseModel], current: Any, depth: int) -> VariantSpec:
    fields = (
        describe_model(current, depth + 1)
        if type(current) is cls
        else describe_model_class(cls, depth + 1)
    )
    kind = getattr(cls, "kind", None)
    label = (
        f"{kind} ({cls.__name__})" if isinstance(kind, str) and kind else cls.__name__
    )
    return VariantSpec(
        id=_registry.variant_id(cls),
        label=label,
        description=_first_doc_line(cls),
        fields=fields,
    )


def _describe_preset(
    preset_id: str,
    label: str,
    description: str | None,
    factory: Callable[[], BaseModel],
    *,
    depth: int,
) -> PresetSpec | None:
    try:
        instance = factory()
    except Exception as exc:  # a preset whose engine is not installed
        _log.debug("Skip preset %s: %s", preset_id, exc)
        return None
    _registry.presets[preset_id] = factory
    return PresetSpec(
        id=preset_id,
        label=label,
        description=description,
        variant=_registry.variant_id(type(instance)),
        values=_values_of(describe_model(instance, depth + 1)),
    )


def _values_of(fields: list[FieldSpec]) -> dict[str, Any]:
    """The default values of a field tree, as the form state the UI shows."""
    values: dict[str, Any] = {}
    for field in fields:
        if field.kind == "object" and field.fields is not None:
            values[field.name] = _values_of(field.fields)
        elif field.kind == "variant":
            continue
        elif not field.unserializable_default:
            values[field.name] = field.default
    return values


# ----------------------------------------------------------------- application
class OptionsError(ValueError):
    """The submitted options do not fit the option model."""


def apply_overrides(
    model: BaseModel, overrides: dict[str, Any], path: str = ""
) -> BaseModel:
    """Return a copy of `model` with the sparse `overrides` applied and validated."""
    cls = type(model)
    updates: dict[str, Any] = {}
    for name, raw in overrides.items():
        if name in (VARIANT_KEY, PRESET_KEY):
            continue
        field_info = cls.model_fields.get(name)
        if field_info is None:
            raise OptionsError(f"{path}{name}: unknown option for {cls.__name__}")
        updates[name] = build_value(
            field_info.annotation, getattr(model, name), raw, f"{path}{name}."
        )
    if not updates:
        return model
    data = {name: getattr(model, name) for name in cls.model_fields}
    data.update(updates)
    try:
        return cls.model_validate(data, by_name=True)
    except ValidationError as exc:
        raise OptionsError(f"{path or cls.__name__}: {exc}") from exc


def build_value(annotation: Any, current: Any, raw: Any, path: str) -> Any:
    """Build the value of one field from its sparse form input."""
    if isinstance(raw, dict) and (VARIANT_KEY in raw or PRESET_KEY in raw):
        return _build_variant(current, raw, path)

    core, _ = _unwrap(annotation)
    members = _union_members(core)
    if (
        isinstance(raw, dict)
        and members
        and all(_is_model(member) for member in members)
    ):
        if isinstance(current, BaseModel):
            return apply_overrides(current, raw, path)
        return _construct(members[0], raw, path)

    try:
        return TypeAdapter(annotation).validate_python(raw)
    except ValidationError as exc:
        raise OptionsError(f"{path.rstrip('.')}: {exc.errors()[0]['msg']}") from exc


def _build_variant(current: Any, raw: dict[str, Any], path: str) -> BaseModel:
    if PRESET_KEY in raw:
        factory = _registry.presets.get(raw[PRESET_KEY])
        if factory is None:
            raise OptionsError(
                f"{path.rstrip('.')}: unknown preset {raw[PRESET_KEY]!r}"
            )
        return apply_overrides(factory(), raw, path)

    cls = _registry.variants.get(raw[VARIANT_KEY])
    if cls is None:
        raise OptionsError(f"{path.rstrip('.')}: unknown variant {raw[VARIANT_KEY]!r}")
    if type(current) is cls:
        return apply_overrides(current, raw, path)
    return _construct(cls, raw, path)


def _construct(cls: type[BaseModel], raw: dict[str, Any], path: str) -> BaseModel:
    instance = _try_instantiate(cls)
    if instance is not None:
        return apply_overrides(instance, raw, path)
    data = {}
    for name, value in raw.items():
        if name in (VARIANT_KEY, PRESET_KEY):
            continue
        field_info = cls.model_fields.get(name)
        if field_info is None:
            raise OptionsError(f"{path}{name}: unknown option for {cls.__name__}")
        data[name] = build_value(field_info.annotation, None, value, f"{path}{name}.")
    try:
        return cls.model_validate(data, by_name=True)
    except ValidationError as exc:
        raise OptionsError(f"{path.rstrip('.') or cls.__name__}: {exc}") from exc


@lru_cache(maxsize=1)
def warm_factories() -> None:
    """Load the Docling plugin factories once, so that all variants are known."""
    for _, factory_getter in _FACTORY_BASES:
        factory_getter(allow_external_plugins=True)

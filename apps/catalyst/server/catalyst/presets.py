"""Named presets that Docling defines for some option classes.

The UI shows them as a "Preset" choice on the field. Choosing one loads the
preset values into the form; the user can still change single fields.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from pydantic import BaseModel

from docling.datamodel.asr_model_specs import AsrModelType
from docling.datamodel.pipeline_options_asr_model import InlineAsrOptions
from docling.datamodel.stage_model_specs import (
    ImageClassificationStagePresetMixin,
    ObjectDetectionStagePresetMixin,
    StagePresetMixin,
)
from catalyst.options_schema import register_preset_provider

Preset = tuple[str, str, str | None, Callable[[], BaseModel]]

_PRESET_MIXINS = (
    StagePresetMixin,
    ObjectDetectionStagePresetMixin,
    ImageClassificationStagePresetMixin,
)


def _stage_presets(cls: type[BaseModel]) -> list[Preset]:
    """Presets of the classes that use one of Docling's preset mixins."""
    if not issubclass(cls, _PRESET_MIXINS):
        return []
    presets: list[Preset] = []
    for preset in cls.list_presets():
        presets.append(
            (
                f"{cls.__name__}:{preset.preset_id}",
                f"{preset.name} ({preset.preset_id})",
                preset.description,
                partial(cls.from_preset, preset.preset_id),
            )
        )
    return presets


def _asr_presets(cls: type[BaseModel]) -> list[Preset]:
    """The Whisper presets that the CLI offers through `--asr-model`."""
    if cls is not InlineAsrOptions:
        return []
    # The CLI keeps the enum-to-options table; reuse it so both stay the same.
    from docling.cli.main import _resolve_asr_options

    return [
        (
            f"asr:{model.value}",
            model.value,
            None,
            partial(lambda m: _resolve_asr_options(m).model_copy(deep=True), model),
        )
        for model in AsrModelType
    ]


def register_presets() -> None:
    register_preset_provider(_stage_presets)
    register_preset_provider(_asr_presets)

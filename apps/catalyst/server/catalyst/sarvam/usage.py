"""Sarvam usage and tables per conversion.

The OCR model runs inside the Docling pipeline and only sees the
`ConversionResult`. It adds the pages of every Sarvam job here, for the cost
shown in the envelope, and the tables that Sarvam read, keyed by that result.
The service takes the entry when the conversion ends. An entry is dropped when
its result is garbage-collected, so a conversion that raises leaves nothing
behind.
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass, field

from catalyst.sarvam.tables import SarvamTable
from docling.datamodel.document import ConversionResult


@dataclass
class SarvamUsage:
    jobs: int = 0
    pages: int = 0
    tables: list[SarvamTable] = field(default_factory=list)


_lock = threading.Lock()
_usage: dict[int, SarvamUsage] = {}


def record_usage(conv_res: ConversionResult, *, pages: int) -> None:
    """Add one Sarvam job with ``pages`` billed pages to the conversion."""
    with _lock:
        usage = _entry(conv_res)
        usage.jobs += 1
        usage.pages += pages


def record_tables(conv_res: ConversionResult, tables: list[SarvamTable]) -> None:
    """Add tables that Sarvam read to the conversion."""
    with _lock:
        _entry(conv_res).tables.extend(tables)


def _entry(conv_res: ConversionResult) -> SarvamUsage:
    """The entry of the conversion; call it with the lock held."""
    key = id(conv_res)
    usage = _usage.get(key)
    if usage is None:
        usage = _usage[key] = SarvamUsage()
        weakref.finalize(conv_res, _forget, key)
    return usage


def take_usage(conv_res: ConversionResult) -> SarvamUsage | None:
    """Remove and return the Sarvam usage of the conversion, if it used Sarvam."""
    with _lock:
        return _usage.pop(id(conv_res), None)


def _forget(key: int) -> None:
    with _lock:
        _usage.pop(key, None)

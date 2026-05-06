"""Selector purposes — the second half of invariant 8's `(domain, purpose)`
namespacing. Single member today; new purposes are a one-line StrEnum
addition plus the call sites that use them. No speculative taxonomy.
"""

from __future__ import annotations

from enum import StrEnum


class SelectorPurpose(StrEnum):
    MAIN_CONTENT = "main_content"

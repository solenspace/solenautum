from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pydantic_ai.models import Model


class LLMProvider(Protocol):
    """Provider that yields a Pydantic AI `Model` bound to its credentials."""

    name: str

    def model(self) -> Model: ...

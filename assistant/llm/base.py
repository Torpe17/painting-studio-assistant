"""Provider-independent LLM interface.

Internal message format (list of dicts):
  {"role": "user", "text": str, "image": bytes | None}
  {"role": "assistant", "text": str, "tool_calls": [ToolCall], "raw": <provider-specific>}
  {"role": "tool", "name": str, "id": str | None, "result": dict}
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str | None = None


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None


class ToolsNotSupported(RuntimeError):
    """The chosen (local) model does not support function calling."""


class LLMProvider(ABC):
    name: str = "base"
    is_local: bool = False  # local = the image never leaves the machine

    def __init__(self, model: str, temperature: float = 0.4):
        self.model = model
        self.temperature = temperature

    @abstractmethod
    def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        json_schema: dict | None = None,
    ) -> LLMResponse:
        """One round: messages -> answer (text and/or tool calls)."""

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"

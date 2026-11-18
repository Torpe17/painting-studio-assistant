"""Local model via Ollama – the image never leaves the machine."""
from __future__ import annotations

import json

import ollama

from .base import LLMProvider, LLMResponse, ToolCall, ToolsNotSupported


class OllamaProvider(LLMProvider):
    name = "ollama"
    is_local = True

    def __init__(self, model: str, host: str = "http://localhost:11434", temperature: float = 0.4):
        super().__init__(model, temperature)
        self.client = ollama.Client(host=host)

    def _messages(self, system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                msg = {"role": "user", "content": m["text"]}
                if m.get("image"):
                    msg["images"] = [m["image"]]
                out.append(msg)
            elif m["role"] == "assistant":
                msg = {"role": "assistant", "content": m.get("text", "")}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"function": {"name": c.name, "arguments": c.args}} for c in m["tool_calls"]]
                out.append(msg)
            elif m["role"] == "tool":
                out.append({"role": "tool", "content": json.dumps(m["result"], ensure_ascii=False),
                            "tool_name": m["name"]})
        return out

    def chat(self, system, messages, tools=None, json_schema=None) -> LLMResponse:
        kwargs = dict(model=self.model, messages=self._messages(system, messages),
                      options={"temperature": self.temperature, "num_ctx": 16384})
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]
        if json_schema:
            kwargs["format"] = json_schema
        try:
            resp = self.client.chat(**kwargs)
        except ollama.ResponseError as exc:
            if tools and "does not support tools" in str(exc):
                raise ToolsNotSupported(str(exc)) from exc
            raise
        msg = resp.message
        calls = [ToolCall(name=c.function.name, args=dict(c.function.arguments or {}))
                 for c in (msg.tool_calls or [])]
        return LLMResponse(text=msg.content or "", tool_calls=calls, raw=None)


def list_ollama_models(host: str = "http://localhost:11434") -> list[str]:
    try:
        return sorted(m.model for m in ollama.Client(host=host).list().models)
    except Exception:  # noqa: BLE001 – Ollama is not running
        return []

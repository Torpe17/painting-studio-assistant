"""Google Gemini (cloud) – google-genai SDK with a manual tool-calling loop."""
from __future__ import annotations

import re
import time

from google import genai
from google.genai import errors, types

from .base import LLMProvider, LLMResponse, ToolCall


class QuotaExceeded(RuntimeError):
    """Daily (not per-minute) quota – retrying will not help."""


class GeminiProvider(LLMProvider):
    name = "gemini"
    is_local = False

    def __init__(self, model: str, api_key: str, temperature: float = 0.4):
        super().__init__(model, temperature)
        if not api_key:
            raise ValueError("GEMINI_API_KEY is missing (see .env.example).")
        # timeout + automatic retry on transient errors (overload, quota)
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=90_000,
            retry_options=types.HttpRetryOptions(
                attempts=4, initial_delay=2.0, max_delay=20.0,
                http_status_codes=[408, 500, 502, 503, 504]),
        ))

    def _contents(self, messages: list[dict]) -> list[types.Content]:
        contents: list[types.Content] = []
        pending_tool_parts: list[types.Part] = []

        def flush():
            if pending_tool_parts:
                contents.append(types.Content(role="user", parts=list(pending_tool_parts)))
                pending_tool_parts.clear()

        for m in messages:
            if m["role"] == "tool":
                pending_tool_parts.append(types.Part.from_function_response(
                    name=m["name"], response={"result": m["result"]}))
                continue
            flush()
            if m["role"] == "user":
                parts = [types.Part.from_text(text=m["text"])]
                if m.get("image"):
                    parts.append(types.Part.from_bytes(data=m["image"], mime_type="image/jpeg"))
                contents.append(types.Content(role="user", parts=parts))
            elif m["role"] == "assistant":
                # send back the original content (to keep thought signatures)
                if m.get("raw") is not None:
                    contents.append(m["raw"])
                else:
                    parts = [types.Part(function_call=types.FunctionCall(name=c.name, args=c.args, id=c.id))
                             for c in m.get("tool_calls", [])]
                    if m.get("text"):
                        parts.insert(0, types.Part.from_text(text=m["text"]))
                    contents.append(types.Content(role="model", parts=parts))
        flush()
        return contents

    def _generate(self, contents, config, max_waits: int = 3):
        """generate_content; on a PER-MINUTE 429 waits the time the API asks for and retries.
        A daily (PerDay) quota error is raised immediately as QuotaExceeded."""
        for attempt in range(max_waits + 1):
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except errors.ClientError as e:
                if e.code != 429:
                    raise
                if "PerDay" in str(e):
                    raise QuotaExceeded(
                        f"The free daily Gemini quota is used up ({self.model}: about 20 requests/day/model). "
                        "Try again tomorrow, pick another Gemini model (each model has its own quota), "
                        "or use the local model.") from e
                if attempt == max_waits:
                    raise
                m = re.search(r"retry in ([\d.]+)s", str(e))
                time.sleep(min(float(m.group(1)) + 1 if m else 30.0, 65.0))

    def chat(self, system, messages, tools=None, json_schema=None) -> LLMResponse:
        cfg = dict(
            system_instruction=system,
            temperature=self.temperature,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if tools:
            cfg["tools"] = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"],
                                          parameters_json_schema=t["parameters"])
                for t in tools])]
        if json_schema:
            cfg["response_mime_type"] = "application/json"
            cfg["response_json_schema"] = json_schema
        resp = self._generate(contents=self._contents(messages), config=types.GenerateContentConfig(**cfg))
        calls = [ToolCall(name=fc.name, args=dict(fc.args or {}), id=fc.id) for fc in (resp.function_calls or [])]
        raw = resp.candidates[0].content if resp.candidates else None
        text = ""
        if raw and raw.parts:
            text = "".join(p.text for p in raw.parts if getattr(p, "text", None) and not getattr(p, "thought", False))
        return LLMResponse(text=text, tool_calls=calls, raw=raw)


def list_gemini_models(api_key: str) -> list[str]:
    """Names of available Gemini models that can handle images (for the UI selector)."""
    client = genai.Client(api_key=api_key)
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions and "gemini" in m.name:
            names.append(m.name.removeprefix("models/"))
    return sorted(names)

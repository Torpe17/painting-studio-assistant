from .base import LLMProvider, LLMResponse, ToolCall, ToolsNotSupported


def make_provider(kind: str, model: str | None = None, temperature: float | None = None) -> LLMProvider:
    """Creates a provider: 'gemini' (cloud) or 'ollama' (local)."""
    from ..config import settings

    temp = settings.temperature if temperature is None else temperature
    if kind == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(model or settings.gemini_model, settings.gemini_api_key, temp)
    if kind == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(model or settings.ollama_model, settings.ollama_host, temp)
    raise ValueError(f"Unknown provider: {kind}")


__all__ = ["LLMProvider", "LLMResponse", "ToolCall", "ToolsNotSupported", "make_provider"]

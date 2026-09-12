"""Provider-safe model adapter with structured failure reporting."""
import os
from dataclasses import dataclass
from typing import Optional


class ModelCallError(RuntimeError):
    """Raised when a configured model provider cannot complete a request."""


@dataclass(frozen=True)
class ModelResult:
    success: bool
    text: str = ""
    provider: str = ""
    error_type: Optional[str] = None
    message: Optional[str] = None


def _extract_chat_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    return str((choices[0].get("message") or {}).get("content") or "")


def _call_openai(prompt: str, key: str, timeout: int) -> str:
    import requests
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": os.environ.get("AIVF_OPENAI_MODEL", "gpt-4o-mini"),
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.7, "max_tokens": 800},
        timeout=timeout,
    )
    response.raise_for_status()
    return _extract_chat_content(response.json())


def _call_groq(prompt: str, key: str, timeout: int) -> str:
    import requests
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": os.environ.get("AIVF_GROQ_MODEL", "llama-3.3-70b-versatile"),
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.7, "max_tokens": 800},
        timeout=timeout,
    )
    response.raise_for_status()
    return _extract_chat_content(response.json())


def _key_provider(key: str) -> Optional[str]:
    """Infer the provider from a recognizable API-key prefix when possible."""
    if key.startswith("gsk_"):
        return "groq"
    if key.startswith("sk-"):
        return "openai"
    return None


def call_model_result(prompt: str, api_key: Optional[str] = None, timeout: int = 15,
                      provider: Optional[str] = None) -> ModelResult:
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    selected = (provider or "").strip().lower()
    if selected and selected not in {"openai", "groq"}:
        raise ValueError(f"Unsupported model provider: {selected}")

    if api_key:
        key = api_key.strip()
        inferred = _key_provider(key)
        if selected and inferred and selected != inferred:
            raise ValueError(
                f"API key appears to belong to {inferred}, but provider={selected!r} was selected"
            )
        selected = selected or inferred
        if not selected:
            raise ValueError("Cannot infer model provider from the supplied API key; pass provider explicitly")
    elif selected == "groq":
        key = os.environ.get("GROQ_API_KEY", "").strip()
    elif selected == "openai":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
    elif os.environ.get("OPENAI_API_KEY"):
        selected, key = "openai", os.environ["OPENAI_API_KEY"].strip()
    elif os.environ.get("GROQ_API_KEY"):
        selected, key = "groq", os.environ["GROQ_API_KEY"].strip()
    else:
        return ModelResult(success=False, error_type="not_configured", message="No model provider is configured")

    if selected not in {"openai", "groq"}:
        raise ValueError(f"Unsupported model provider: {selected}")
    if not key:
        return ModelResult(success=False, provider=selected, error_type="not_configured",
                           message=f"{selected} provider is not configured")

    try:
        text = _call_groq(prompt, key, timeout) if selected == "groq" else _call_openai(prompt, key, timeout)
        if not text:
            return ModelResult(success=False, provider=selected, error_type="empty_response",
                               message="Provider returned no text")
        return ModelResult(success=True, text=text, provider=selected)
    except Exception as exc:
        return ModelResult(success=False, provider=selected, error_type=type(exc).__name__,
                           message=f"{selected} model request failed")


def call_model(prompt: str, api_key: Optional[str] = None, timeout: int = 15,
               provider: Optional[str] = None) -> str:
    """Backwards-compatible string API; never crosses provider boundaries."""
    result = call_model_result(prompt, api_key=api_key, timeout=timeout, provider=provider)
    if result.success:
        return result.text
    if result.error_type == "not_configured":
        return ""
    raise ModelCallError(result.message or "model request failed")

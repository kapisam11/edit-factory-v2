"""Provider-safe adapter for optional model-driven reviews and rewrites."""
import os
from typing import Optional


class ModelCallError(RuntimeError):
    """Raised when a configured model provider cannot complete a request."""


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
        json={"model": os.environ.get("AIVF_GROQ_MODEL", "llama-3.1-8b-instant"),
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.7, "max_tokens": 800},
        timeout=timeout,
    )
    response.raise_for_status()
    return _extract_chat_content(response.json())


def call_model(prompt: str, api_key: Optional[str] = None, timeout: int = 15,
               provider: Optional[str] = None) -> str:
    """Call exactly one configured provider without credential cross-over."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    selected = (provider or "").strip().lower()
    if api_key:
        key = api_key
        selected = selected or ("groq" if key.startswith("gsk_") else "openai")
    elif selected == "groq":
        key = os.environ.get("GROQ_API_KEY", "")
    elif selected == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
    elif os.environ.get("OPENAI_API_KEY"):
        selected, key = "openai", os.environ["OPENAI_API_KEY"]
    elif os.environ.get("GROQ_API_KEY"):
        selected, key = "groq", os.environ["GROQ_API_KEY"]
    else:
        return ""

    if selected not in {"openai", "groq"}:
        raise ValueError(f"Unsupported model provider: {selected}")

    try:
        return _call_groq(prompt, key, timeout) if selected == "groq" else _call_openai(prompt, key, timeout)
    except Exception as exc:
        raise ModelCallError(f"{selected} model request failed") from exc

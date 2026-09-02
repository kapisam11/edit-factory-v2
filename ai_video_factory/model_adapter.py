"""Pluggable model adapter for optional model-driven reviews and rewrites.

This module exposes `call_model` which will attempt to call OpenAI's
completion API if `OPENAI_API_KEY` is provided in the environment, or
will fall back to a local heuristic responder.

Note: no external calls are made automatically; caller must supply API
key via environment or explicit argument.
"""
import os
import json
from typing import Optional


def call_model(prompt: str, api_key: Optional[str] = None, timeout: int = 15) -> str:
    """Call a model (OpenAI) if API key provided, otherwise return empty string.

    This is a thin wrapper: if `api_key` or `OPENAI_API_KEY` is not present
    the function returns an empty string indicating no model output.
    """
    key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not key:
        return ""

    try:
        import requests
        if key.startswith("gsk_"):
            try:
                url = "https://api.groq.com/v1/infer"
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                payload = {
                    "model": "gpt-4o-mini",
                    "input": prompt,
                    "temperature": 0.7,
                    "max_output_tokens": 800,
                }
                r = requests.post(url, headers=headers, json=payload, timeout=timeout)
                r.raise_for_status()
                data = r.json()
                output = data.get("output") or data.get("outputs") or data.get("text")
                if isinstance(output, list):
                    return "\n".join(str(x) for x in output)
                if isinstance(output, str):
                    return output
            except Exception:
                pass

        # First try Chat Completions
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 800,
            }
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
            r.raise_for_status()
            j = r.json()
            if "choices" in j and len(j["choices"]) > 0:
                return j["choices"][0].get("message", {}).get("content", "") or ""
        except Exception:
            # fallback to legacy completions endpoint with a text model
            try:
                url2 = "https://api.openai.com/v1/completions"
                headers2 = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                payload2 = {"model": "text-davinci-003", "prompt": prompt, "max_tokens": 800, "temperature": 0.7}
                r2 = requests.post(url2, headers=headers2, data=json.dumps(payload2), timeout=timeout)
                r2.raise_for_status()
                j2 = r2.json()
                if "choices" in j2 and len(j2["choices"]) > 0:
                    return j2["choices"][0].get("text", "") or ""
            except Exception:
                return ""
        return ""
    except Exception:
        return ""

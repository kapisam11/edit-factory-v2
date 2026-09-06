import pytest

from ai_video_factory import model_adapter


def test_groq_failure_never_falls_back_to_openai(monkeypatch):
    monkeypatch.setattr(
        model_adapter,
        "_call_groq",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        model_adapter,
        "_call_openai",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    with pytest.raises(model_adapter.ModelCallError):
        model_adapter.call_model("hello", api_key="gsk_test")


def test_structured_result_reports_provider_failure(monkeypatch):
    monkeypatch.setattr(
        model_adapter,
        "_call_groq",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = model_adapter.call_model_result("hello", api_key="gsk_test")
    assert result.success is False
    assert result.provider == "groq"
    assert result.error_type == "RuntimeError"


def test_invalid_provider_is_rejected():
    with pytest.raises(ValueError):
        model_adapter.call_model("hello", api_key="x", provider="other")

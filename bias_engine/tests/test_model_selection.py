import os
import pytest
from bias_engine.llm_providers import create_provider_for_model, THKIProvider, GeminiProvider, OpenAIProvider, OpenAICompatibleProvider
from bias_engine.thki_discovery import check_and_update_thki_models


def test_create_provider_for_model():
    p_thki = create_provider_for_model("thki", "openai-gpt5.4-mini")
    assert isinstance(p_thki, THKIProvider)
    assert p_thki.model == "openai-gpt5.4-mini"

    p_gemini = create_provider_for_model("gemini", "gemini-3.5-flash-lite")
    assert isinstance(p_gemini, GeminiProvider)
    assert p_gemini.model == "gemini-3.5-flash-lite"

    p_openai = create_provider_for_model("openai", "gpt-4o-mini")
    assert isinstance(p_openai, OpenAIProvider)
    assert p_openai.model == "gpt-4o-mini"

    p_local = create_provider_for_model("local", "llama3.2")
    assert isinstance(p_local, OpenAICompatibleProvider)
    assert p_local.model == "llama3.2"


def test_thki_model_discovery(tmp_path):
    res = check_and_update_thki_models(data_dir=tmp_path, force=False)
    assert "models" in res
    assert len(res["models"]) > 0
    assert "last_checked" in res
    # Ensure recommended model is present
    model_ids = [m["id"] for m in res["models"]]
    assert "openai-gpt5.4-mini" in model_ids

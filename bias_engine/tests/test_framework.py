"""
Unit tests for Bias Framework.
"""
from bias_engine.framework import get_default_framework, load_framework


def test_default_framework_categories():
    fw = get_default_framework()
    assert fw.name == "autocomplete_bias"
    keys = fw.category_keys
    assert "political" in keys
    assert "accusation" in keys
    assert "conspiracy" in keys
    assert "sexism" in keys
    assert "racism" in keys
    assert "religious" in keys


def test_framework_mouseover_composition():
    fw = get_default_framework()
    # Unbiased -> neutral message
    assert "neutral" in fw.compose_mouseover({})
    assert "neutral" in fw.compose_mouseover({"political": 0.0})

    # Single category
    mo = fw.compose_mouseover({"conspiracy": 0.75})
    assert "conspiracy" in mo
    assert "0.75" in mo

    # Multi category
    mo_multi = fw.compose_mouseover({"political": 0.45, "accusation": 0.80})
    assert "political" in mo_multi
    assert "accusatory" in mo_multi or "accusation" in mo_multi

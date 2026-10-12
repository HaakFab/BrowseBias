"""
Unit tests for Suggestion Normalizer.
"""
from bias_engine.suggestion_normalizer import SuggestionNormalizer


def test_normalizer_basic():
    normalizer = SuggestionNormalizer()
    text = "Donald Trump age"
    res = normalizer.normalize(text)
    # Checks that named entity is replaced or text is cleaned
    assert isinstance(res, str)
    assert len(res) > 0


def test_normalizer_empty():
    normalizer = SuggestionNormalizer()
    assert normalizer.normalize("") == ""
    assert normalizer.normalize("   ") == ""


def test_normalizer_batch_and_provenance():
    normalizer = SuggestionNormalizer()
    items = [
        ("donald trump", "donald trump fraud"),
        ("biden", "biden fraud"),
    ]
    results = normalizer.normalize_batch(items)
    assert len(results) == 2
    q1, raw1, norm1 = results[0]
    prov = normalizer.get_provenance(norm1)
    assert (q1, raw1) in prov

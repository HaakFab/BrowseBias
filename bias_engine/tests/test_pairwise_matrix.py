"""
Unit tests for Pairwise Comparison Matrix (PCM).
"""
from bias_engine.pairwise_matrix import PairwiseMatrix


def test_pcm_basic_comparisons():
    pcm = PairwiseMatrix(category="political", model="gemini")
    pcm.add_comparison("item_a", "item_b", outcome=1.0)
    w_a, w_b, ties = pcm.get_record("item_a", "item_b")
    assert w_a == 1
    assert w_b == 0
    assert ties == 0

    # Symmetry check from b's perspective
    wb_rev, wa_rev, _ = pcm.get_record("item_b", "item_a")
    assert wb_rev == 0
    assert wa_rev == 1


def test_pcm_listwise_extraction():
    pcm = PairwiseMatrix(category="conspiracy", model="gemini")
    ranking = ["most_biased", "mid_biased", "least_biased"]
    added = pcm.add_listwise_ranking(ranking)
    # For k=3, k*(k-1)/2 = 3 comparisons
    assert added == 3

    w_most_mid, _, _ = pcm.get_record("most_biased", "mid_biased")
    w_most_least, _, _ = pcm.get_record("most_biased", "least_biased")
    w_mid_least, _, _ = pcm.get_record("mid_biased", "least_biased")

    assert w_most_mid == 1
    assert w_most_least == 1
    assert w_mid_least == 1


def test_pcm_combine_models():
    pcm_model1 = PairwiseMatrix(category="racism", model="model_1")
    pcm_model2 = PairwiseMatrix(category="racism", model="model_2")

    pcm_model1.add_comparison("x", "y", outcome=1.0)
    pcm_model2.add_comparison("x", "y", outcome=1.0)
    pcm_model2.add_comparison("x", "z", outcome=1.0)

    combined = PairwiseMatrix.combine([pcm_model1, pcm_model2], category="racism")
    w_xy, _, _ = combined.get_record("x", "y")
    w_xz, _, _ = combined.get_record("x", "z")

    assert w_xy == 2
    assert w_xz == 1


def test_pcm_serialization():
    pcm = PairwiseMatrix(category="sexism", model="test_model")
    pcm.add_comparison("p", "q", outcome=1.0)
    data = pcm.to_dict()
    restored = PairwiseMatrix.from_dict(data)
    w_p, w_q, _ = restored.get_record("p", "q")
    assert w_p == 1
    assert w_q == 0

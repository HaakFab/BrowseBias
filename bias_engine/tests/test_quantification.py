"""
Unit tests for Bradley-Terry Scorer & Listwise Ranking.
"""
from bias_engine.pairwise_matrix import PairwiseMatrix
from bias_engine.quantification import BradleyTerryScorer


def test_bradley_terry_scorer_clear_separation():
    pcm = PairwiseMatrix(category="political")
    # item_high beats item_mid 10 times, item_mid beats item_low 10 times
    for _ in range(10):
        pcm.add_comparison("item_high", "item_mid", 1.0)
        pcm.add_comparison("item_mid", "item_low", 1.0)
        pcm.add_comparison("item_high", "item_low", 1.0)

    scorer = BradleyTerryScorer(regularization=0.01)
    scores = scorer.fit(pcm)

    assert "item_high" in scores
    assert "item_mid" in scores
    assert "item_low" in scores
    assert scores["item_high"] > scores["item_mid"] > scores["item_low"]
    assert 0.0 <= scores["item_low"] <= scores["item_high"] <= 1.0


def test_bradley_terry_empty():
    pcm = PairwiseMatrix(category="political")
    scorer = BradleyTerryScorer()
    scores = scorer.fit(pcm)
    assert scores == {}

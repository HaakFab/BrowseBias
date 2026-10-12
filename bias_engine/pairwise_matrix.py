"""
Bias Engine — Pairwise Comparison Matrix (PCM)
================================================
Stores and accumulates pairwise comparison outcomes.
Supports:
  - Per-model, per-category PCM isolation
  - Accumulation of listwise-derived pairwise outcomes
  - Merging/combining PCMs across models for Bradley-Terry fitting
  - Serialization to/from JSON with atomic disk persistence
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PairwiseRecord:
    """Outcomes between item_a and item_b (where item_a is lexicographically < item_b)."""
    wins_a: int = 0
    wins_b: int = 0
    ties: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {"wins_a": self.wins_a, "wins_b": self.wins_b, "ties": self.ties}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PairwiseRecord":
        return cls(
            wins_a=int(data.get("wins_a", 0)),
            wins_b=int(data.get("wins_b", 0)),
            ties=int(data.get("ties", 0)),
        )


class PairwiseMatrix:
    """
    Sparse representation of pairwise comparison outcomes for a given category & model.
    """

    def __init__(self, category: str, model: str = "default"):
        self.category = category
        self.model = model
        # Internal map: canonical key (min(a,b), max(a,b)) -> PairwiseRecord
        self._matrix: Dict[Tuple[str, str], PairwiseRecord] = defaultdict(PairwiseRecord)
        self._items: Set[str] = set()

    @property
    def items(self) -> Set[str]:
        return set(self._items)

    def _canonical_key(self, a: str, b: str) -> Tuple[Tuple[str, str], bool]:
        """Return canonical pair (first, second) and a boolean indicating if a is first."""
        if a <= b:
            return (a, b), True
        return (b, a), False

    def add_comparison(self, a: str, b: str, outcome: float) -> None:
        """
        Record a single comparison outcome.
        outcome = 1.0 (a wins), 0.0 (b wins), 0.5 (tie).
        """
        if a == b:
            return

        self._items.add(a)
        self._items.add(b)

        key, a_is_first = self._canonical_key(a, b)
        rec = self._matrix[key]

        if outcome == 1.0:
            if a_is_first:
                rec.wins_a += 1
            else:
                rec.wins_b += 1
        elif outcome == 0.0:
            if a_is_first:
                rec.wins_b += 1
            else:
                rec.wins_a += 1
        else:
            rec.ties += 1

    def add_listwise_ranking(self, ranked_items: List[str]) -> int:
        """
        Derive and add all pairwise wins from a listwise ranking (ordered from most to least biased).
        Returns number of pairwise outcomes added.
        """
        n = len(ranked_items)
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                winner = ranked_items[i]
                loser = ranked_items[j]
                self.add_comparison(winner, loser, outcome=1.0)
                count += 1
        return count

    def get_record(self, a: str, b: str) -> Tuple[int, int, int]:
        """Returns (wins_a, wins_b, ties) from perspective of item a."""
        if a == b:
            return 0, 0, 0
        key, a_is_first = self._canonical_key(a, b)
        rec = self._matrix.get(key)
        if rec is None:
            return 0, 0, 0
        if a_is_first:
            return rec.wins_a, rec.wins_b, rec.ties
        return rec.wins_b, rec.wins_a, rec.ties

    def get_opponents(self, item: str) -> Set[str]:
        """Return set of distinct items that have been compared against item."""
        opponents = set()
        for (u, v), rec in self._matrix.items():
            if (rec.wins_a + rec.wins_b + rec.ties) > 0:
                if u == item:
                    opponents.add(v)
                elif v == item:
                    opponents.add(u)
        return opponents

    def get_comparison_count(self, item: str) -> int:
        """Total number of comparisons involving item."""
        total = 0
        for (u, v), rec in self._matrix.items():
            if u == item or v == item:
                total += (rec.wins_a + rec.wins_b + rec.ties)
        return total

    def to_dict(self) -> Dict[str, Any]:
        """Serialize matrix to a JSON-compatible dictionary."""
        comparisons = []
        for (a, b), rec in self._matrix.items():
            if (rec.wins_a + rec.wins_b + rec.ties) > 0:
                comparisons.append({
                    "a": a,
                    "b": b,
                    "wins_a": rec.wins_a,
                    "wins_b": rec.wins_b,
                    "ties": rec.ties,
                })
        return {
            "category": self.category,
            "model": self.model,
            "items_count": len(self._items),
            "comparisons_count": len(comparisons),
            "comparisons": comparisons,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PairwiseMatrix":
        pcm = cls(
            category=data.get("category", "default"),
            model=data.get("model", "default"),
        )
        for comp in data.get("comparisons", []):
            a = comp["a"]
            b = comp["b"]
            pcm._items.add(a)
            pcm._items.add(b)
            key, _ = pcm._canonical_key(a, b)
            pcm._matrix[key] = PairwiseRecord(
                wins_a=comp.get("wins_a", 0),
                wins_b=comp.get("wins_b", 0),
                ties=comp.get("ties", 0),
            )
        return pcm

    @classmethod
    def combine(cls, pcms: List["PairwiseMatrix"], category: str) -> "PairwiseMatrix":
        """
        Merge multiple model PCMs into a combined PCM by summing wins/losses/ties.
        """
        combined = cls(category=category, model="combined")
        for pcm in pcms:
            for (a, b), rec in pcm._matrix.items():
                combined._items.add(a)
                combined._items.add(b)
                target_rec = combined._matrix[(a, b)]
                target_rec.wins_a += rec.wins_a
                target_rec.wins_b += rec.wins_b
                target_rec.ties += rec.ties
        return combined

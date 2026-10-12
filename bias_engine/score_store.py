"""
Bias Engine — Score Store & Lexicon Bridge
============================================
Maintains the in-memory score registry across all bias categories,
computes continuous numerical scores, composes mouseover tooltips,
and generates the production `lexicon.json`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .framework import BiasFramework

logger = logging.getLogger(__name__)


@dataclass
class SuggestionScoreRecord:
    """Complete scoring record for a normalized suggestion template."""
    text: str
    scores: Dict[str, float] = field(default_factory=dict)   # category_key -> score in [0.0, 1.0]
    score: float = 0.0                                       # continuous max score across categories
    mouseover: str = "This suggestion appears neutral."
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    @property
    def max_score(self) -> float:
        """Alias for backward compatibility."""
        return self.score

    def recompute(self, framework: BiasFramework):
        """Recompute score and mouseover tooltip from current category scores."""
        if self.scores:
            self.score = round(max(self.scores.values()), 4)
        else:
            self.score = 0.0

        self.mouseover = framework.compose_mouseover(self.scores)
        self.updated_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "score": self.score,
            "scores": self.scores,
            "mouseover": self.mouseover,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SuggestionScoreRecord":
        score_val = float(data.get("score", data.get("maxScore", 0.0)))
        return cls(
            text=data["text"],
            scores=data.get("scores", {}),
            score=score_val,
            mouseover=data.get("mouseover", "This suggestion appears neutral."),
            updated_at=data.get("updatedAt", datetime.utcnow().isoformat() + "Z"),
        )


class ScoreStore:
    """
    In-memory and file-backed store for all scored suggestions across all categories.
    """

    def __init__(self, framework: BiasFramework):
        self.framework = framework
        self._records: Dict[str, SuggestionScoreRecord] = {}

    def get_record(self, text: str) -> Optional[SuggestionScoreRecord]:
        return self._records.get(text)

    def get_scores(self, text: str) -> Dict[str, float]:
        rec = self._records.get(text)
        return rec.scores if rec else {}

    def get_score(self, text: str) -> float:
        rec = self._records.get(text)
        return rec.score if rec else 0.0

    def get_max_score(self, text: str) -> float:
        return self.get_score(text)

    def get_mouseover(self, text: str) -> str:
        rec = self._records.get(text)
        return rec.mouseover if rec else "This suggestion appears neutral."

    def set_category_score(self, text: str, category_key: str, score: float):
        """Set or update a single category score for an item and refresh derived fields."""
        rec = self._records.get(text)
        if rec is None:
            rec = SuggestionScoreRecord(text=text)
            self._records[text] = rec
        rec.scores[category_key] = round(float(score), 4)
        rec.recompute(self.framework)

    def bulk_update_category_scores(self, category_key: str, scores: Dict[str, float]):
        """Batch update scores for a specific category."""
        for text, score in scores.items():
            self.set_category_score(text, category_key, score)

    def register_unbiased(self, text: str):
        """Mark an item as confirmed unbiased (score 0 across all categories)."""
        rec = self._records.get(text)
        if rec is None:
            rec = SuggestionScoreRecord(text=text)
            self._records[text] = rec
        for cat in self.framework.categories:
            rec.scores[cat.key] = 0.0
        rec.recompute(self.framework)

    def to_lexicon_dict(self) -> Dict[str, Any]:
        """
        Generate lexicon dictionary served to the extension via /api/lexicon.

        Structure:
          - Each key is a normalized suggestion text
          - Value contains numerical score [0.0, 1.0], per-category scores, and mouseover text.
        """
        out: Dict[str, Any] = {}
        for text, rec in self._records.items():
            out[text] = {
                "score": rec.score,
                "scores": rec.scores,
                "mouseover": rec.mouseover,
            }
        return out

    def load_from_dict(self, data: Dict[str, Any]):
        """Load state from serialized dict."""
        self._records.clear()
        for text, item in data.items():
            if isinstance(item, dict):
                rec = SuggestionScoreRecord.from_dict({"text": text, **item})
                self._records[text] = rec

    @property
    def size(self) -> int:
        return len(self._records)

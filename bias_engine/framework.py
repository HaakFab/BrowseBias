"""
Bias Engine — Multi-Category Bias Framework
=============================================
Defines the pluggable bias framework with multiple independent bias
categories ("chapters"), each with its own definition and mouseover
interpretation templates.

The framework drives:
  - Identification prompts (which categories to tag)
  - Quantification prompts (per-category ranking)
  - Mouseover text composition
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class BiasCategory:
    """
    A single bias category ("chapter") in the framework.

    Each category is independently scored on a continuous [0.0, 1.0] scale.
    """
    key: str                    # machine identifier, e.g., "conspiracy"
    short_key: str              # single/two-letter key for compact prompts, e.g., "c"
    name: str                   # human-readable, e.g., "Conspiracy Theory"
    definition: str             # full textual definition for LLM prompts
    mouseover_template: str = "This suggestion shows {name} (score: {score:.2f})."

    def format_mouseover(self, score: float) -> str:
        """Format the mouseover text for this category."""
        return self.mouseover_template.format(
            name=self.name.lower(),
            score=score,
        )


@dataclass
class BiasFramework:
    """
    Multi-category bias framework.

    Contains multiple independent bias categories, each with its own definition.
    Each category produces continuous scores via Bradley-Terry modeling.
    """
    name: str
    description: str = ""
    categories: List[BiasCategory] = field(default_factory=list)

    @property
    def category_keys(self) -> List[str]:
        return [c.key for c in self.categories]

    @property
    def category_short_keys(self) -> Dict[str, str]:
        """Map full key → short key for compact prompts."""
        return {c.key: c.short_key for c in self.categories}

    @property
    def short_key_to_key(self) -> Dict[str, str]:
        """Map short key → full key for response parsing."""
        return {c.short_key: c.key for c in self.categories}

    def get_category(self, key: str) -> Optional[BiasCategory]:
        for c in self.categories:
            if c.key == key:
                return c
        return None

    def compose_mouseover(
        self,
        category_scores: Dict[str, float],
        threshold: float = 0.01,
    ) -> str:
        """
        Compose a mouseover tooltip from all active categories.

        Only categories with score > threshold are included.
        Score == 0.0 exactly means "not flagged at all".
        """
        parts = []
        for cat in self.categories:
            score = category_scores.get(cat.key, 0.0)
            if score > threshold:
                parts.append(cat.format_mouseover(score))
        if not parts:
            return "This suggestion appears neutral."
        return " ".join(parts)


# ─── Framework Loading ───────────────────────────────────────────────────────


def _parse_category(raw: Dict) -> BiasCategory:
    sk = raw.get("short_key") or raw.get("short_code") or raw.get("key", "unk")[:3]
    return BiasCategory(
        key=raw["key"],
        short_key=str(sk),
        name=raw["name"],
        definition=raw["definition"],
        mouseover_template=raw.get(
            "mouseover_template",
            "This suggestion shows {name} (score: {score:.2f}).",
        ),
    )


def load_framework(path: str) -> BiasFramework:
    """Load a bias framework from a YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return BiasFramework(
        name=raw.get("name", "unnamed"),
        description=raw.get("description", ""),
        categories=[_parse_category(c) for c in raw.get("categories", [])],
    )


def get_default_framework() -> BiasFramework:
    """Load the built-in default framework."""
    default_path = Path(__file__).parent / "default_framework.yaml"
    if default_path.exists():
        return load_framework(str(default_path))
    return _build_default_framework()


# ─── Default Framework (hardcoded fallback) ──────────────────────────────────


def _build_default_framework() -> BiasFramework:
    return BiasFramework(
        name="autocomplete_bias",
        description="Multi-category bias framework for autocomplete suggestions.",
        categories=[
            BiasCategory(
                key="political",
                short_key="p",
                name="Political Ideology Bias",
                definition=(
                    "Suggestions that favor, amplify, or demonize a political "
                    "position, party, leader, or ideology through loaded, "
                    "evaluative, or one-sided language."
                ),
                mouseover_template=(
                    "This suggestion reflects political ideology bias "
                    "(score: {score:.2f})."
                ),
            ),
            BiasCategory(
                key="accusation",
                short_key="a",
                name="Accusation / Defamation",
                definition=(
                    "Suggestions that accuse, defame, or make unsubstantiated "
                    "negative claims about individuals, groups, or institutions "
                    "without factual basis or in a sensationalized manner."
                ),
                mouseover_template=(
                    "This suggestion contains accusatory or defamatory "
                    "language (score: {score:.2f})."
                ),
            ),
            BiasCategory(
                key="conspiracy",
                short_key="c",
                name="Conspiracy Theory",
                definition=(
                    "Suggestions that promote, lend credibility to, or "
                    "normalize conspiracy theories, unsubstantiated cover-up "
                    "narratives, or paranoid framing."
                ),
                mouseover_template=(
                    "This suggestion is associated with conspiracy theories "
                    "(score: {score:.2f})."
                ),
            ),
            BiasCategory(
                key="sexism",
                short_key="s",
                name="Sexism / Gender Bias",
                definition=(
                    "Suggestions that reinforce gender stereotypes, demean "
                    "a gender, or contain gendered slurs, assumptions, or "
                    "objectifying language."
                ),
                mouseover_template=(
                    "This suggestion reflects sexism or gender bias "
                    "(score: {score:.2f})."
                ),
            ),
            BiasCategory(
                key="racism",
                short_key="r",
                name="Racism / Ethnic Bias",
                definition=(
                    "Suggestions that associate ethnic, racial, or national "
                    "groups with negative attributes, reinforce stereotypes, "
                    "or use dehumanizing language."
                ),
                mouseover_template=(
                    "This suggestion reflects racism or ethnic bias "
                    "(score: {score:.2f})."
                ),
            ),
            BiasCategory(
                key="religious",
                short_key="re",
                name="Religious Bias",
                definition=(
                    "Suggestions that demonize, mock, or unfairly characterize "
                    "religious groups, beliefs, or practices."
                ),
                mouseover_template=(
                    "This suggestion reflects religious bias "
                    "(score: {score:.2f})."
                ),
            ),
        ],
    )

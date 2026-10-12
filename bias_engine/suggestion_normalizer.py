"""
Bias Engine — Suggestion Normalization
========================================
Normalizes raw autocomplete suggestions using NLP (spaCy) entity recognition.

Replaces specific named entities with canonical entity tags:
  - "Donald Trump age"       -> "[PERSON] age"
  - "Donald Trump fraud"     -> "[PERSON] fraud"
  - "Apple bankrupt"         -> "[ORG] bankrupt"
  - "Germany economy"        -> "[GPE] economy"
  - "climate change hoax"    -> "climate change hoax" (no named entity, preserved)

This groups queries about different specific people, organizations, or countries
into generalized suggestion templates, drastically reducing the unique item count
and allowing bias evaluations to generalize across targets.
"""
from __future__ import annotations

import re
import logging
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Canonical mapping from spaCy entity labels to normalized tags
ENTITY_TAG_MAP = {
    "PERSON": "[PERSON]",
    "PER": "[PERSON]",
    "ORG": "[ORG]",
    "GPE": "[GPE]",          # Countries, cities, states
    "LOC": "[LOC]",          # Non-GPE locations, mountain ranges, bodies of water
    "NORP": "[NORP]",        # Nationalities or religious or political groups
    "FAC": "[FACILITY]",
    "PRODUCT": "[PRODUCT]",
    "EVENT": "[EVENT]",
    "WORK_OF_ART": "[WORK_OF_ART]",
    "LAW": "[LAW]",
    "LANGUAGE": "[LANGUAGE]",
}


class SuggestionNormalizer:
    """
    NLP-based suggestion normalizer using spaCy NER.
    """

    def __init__(self, spacy_model: str = "en_core_web_sm"):
        self.spacy_model_name = spacy_model
        self._nlp = None
        self._provenance: Dict[str, Set[Tuple[str, str]]] = {}

    def _get_nlp(self):
        """Lazy load spaCy model with graceful fallback."""
        if self._nlp is None:
            try:
                import spacy
                try:
                    self._nlp = spacy.load(self.spacy_model_name)
                except Exception:
                    logger.warning(
                        "spaCy model '%s' not found. Attempting to load blank 'en' or download...",
                        self.spacy_model_name,
                    )
                    try:
                        self._nlp = spacy.load("en_core_web_sm")
                    except Exception:
                        self._nlp = spacy.blank("en")
            except ImportError:
                logger.warning(
                    "spaCy not installed. Normalization will use rule-based fallback."
                )
                self._nlp = False
        return self._nlp

    def normalize(self, raw_text: str, query: Optional[str] = None) -> str:
        """
        Normalize a suggestion text by replacing named entities with entity tags.

        Args:
            raw_text: The full autocomplete suggestion (e.g. 'Donald Trump fraud')
            query: The root search query typed by the user (optional, for provenance)

        Returns:
            Normalized suggestion template (e.g. '[PERSON] fraud')
        """
        if not raw_text:
            return ""

        text = raw_text.strip()
        # Clean basic whitespace and non-printable chars
        text = re.sub(r"\s+", " ", text)

        nlp = self._get_nlp()
        if nlp:
            doc = nlp(text)
            # Replace entities in reverse order (to preserve character offsets)
            entities = sorted(doc.ents, key=lambda e: e.start_char, reverse=True)
            normalized = text
            for ent in entities:
                tag = ENTITY_TAG_MAP.get(ent.label_, f"[{ent.label_}]")
                normalized = (
                    normalized[: ent.start_char]
                    + tag
                    + normalized[ent.end_char :]
                )
            result = re.sub(r"\s+", " ", normalized).strip()
        else:
            # Fallback simple cleaning without NER
            result = text

        # Record provenance if query provided
        if query is not None:
            if result not in self._provenance:
                self._provenance[result] = set()
            self._provenance[result].add((query.strip(), raw_text.strip()))

        return result

    def normalize_batch(
        self, items: List[Tuple[str, str]]
    ) -> List[Tuple[str, str, str]]:
        """
        Normalize a batch of (query, raw_suggestion) pairs.

        Returns:
            List of (query, raw_suggestion, normalized_suggestion)
        """
        results = []
        for q, raw in items:
            norm = self.normalize(raw, query=q)
            results.append((q, raw, norm))
        return results

    def get_provenance(self, normalized_suggestion: str) -> Set[Tuple[str, str]]:
        """Retrieve all (query, raw_suggestion) pairs that mapped to this normalized string."""
        return self._provenance.get(normalized_suggestion, set())

    def clear_provenance(self):
        self._provenance.clear()

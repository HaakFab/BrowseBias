"""
Bias Engine — Multi-Category Bias Identification
==================================================
Fast, cost-effective LLM tagger that classifies normalized autocomplete suggestions
across multiple bias categories in batches.

Uses token-preserving, ultra-compact response schema:
  `[{"i": 0, "p": 0, "a": 1, "c": 0, "s": 0, "r": 0, "re": 0}, ...]`
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from .framework import BiasFramework
from .llm_providers import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class IdentificationResult:
    """Result of identifying bias categories for a single suggestion."""
    text: str
    categories: Dict[str, bool] = field(default_factory=dict)
    flagged_any: bool = False
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def is_flagged_for(self, category_key: str) -> bool:
        return self.categories.get(category_key, False)


class BiasIdentifier:
    """
    Classifies normalized suggestions against framework categories using an LLM.
    """

    def __init__(
        self,
        framework: BiasFramework,
        provider: LLMProvider,
        batch_size: int = 50,
    ):
        self.framework = framework
        self.provider = provider
        self.batch_size = batch_size

    def _build_system_prompt(self) -> str:
        """Construct compact system prompt with definitions and JSON object schema."""
        categories_def = []
        short_keys = []
        for cat in self.framework.categories:
            categories_def.append(f"- '{cat.short_key}' ({cat.name}): {cat.definition}")
            short_keys.append(f'"{cat.short_key}": 0 or 1')

        keys_schema = ", ".join(short_keys)
        prompt = (
            "You are an expert annotator for search autocomplete bias.\n"
            "Classify each numbered suggestion template across the following categories:\n\n"
            + "\n".join(categories_def)
            + "\n\n"
            "You MUST return a pure JSON object with a 'results' array where each element has 'i' (integer index) "
            f"and 0/1 indicators for each category: {keys_schema}.\n"
            "Example format:\n"
            "{\"results\": [{\"i\": 0, " + ", ".join([f'"{c.short_key}": 0' for c in self.framework.categories]) + "}]}\n"
            "Do NOT include explanations or markdown prose. Return pure JSON."
        )
        return prompt

    def _parse_response(
        self, raw_response: str, expected_count: int
    ) -> List[Dict[str, int]]:
        """Parse LLM JSON response with fallback sanitation and truncated repair."""
        text = raw_response.strip()
        # Strip markdown code blocks if present (handling leading/trailing whitespace or text)
        if "```" in text:
            code_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            if code_match:
                text = code_match.group(1).strip()
            else:
                text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text).strip()

        # Direct JSON decode
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("results", "suggestions", "data", "items", "classifications"):
                    if key in data and isinstance(data[key], list):
                        return data[key]
                # Dict with string integer keys: {"0": {...}, "1": {...}}
                if all(k.isdigit() for k in data.keys() if isinstance(data[k], dict)):
                    res = []
                    for k, v in data.items():
                        item = dict(v)
                        item.setdefault("i", int(k))
                        res.append(item)
                    return res
                # Single classified object: {"i": 0, "p": 0, ...}
                if "i" in data or any(c.short_key in data for c in self.framework.categories):
                    data.setdefault("i", 0)
                    return [data]
        except Exception as e:
            logger.warning("Failed to parse JSON directly (%s). Attempting recovery.", e)

        # Truncated or malformed recovery: find all embedded JSON objects {"i": N, ...}
        # e.g., if generation hit max_tokens midway through
        objects = []
        pattern = re.compile(r'\{\s*"i"\s*:\s*(\d+)[^}]*\}')
        for match in pattern.finditer(text):
            try:
                obj = json.loads(match.group(0))
                if isinstance(obj, dict) and "i" in obj:
                    objects.append(obj)
            except Exception:
                continue

        if objects:
            logger.info("Recovered %d items from truncated/partially-formatted LLM response.", len(objects))
            return objects

        # Regex fallback for embedded JSON array [...]
        match_arr = re.search(r"\[\s*\{.*?\}\s*\]", text, re.DOTALL)
        if match_arr:
            try:
                arr = json.loads(match_arr.group(0))
                if isinstance(arr, list):
                    return arr
            except Exception:
                pass

        logger.error("Could not parse LLM identification response:\n%s", raw_response[:300])
        return []

    def _identify_chunk_with_fallback(self, chunk: List[str]) -> List[IdentificationResult]:
        """Classify a chunk of suggestions, automatically subdividing if the model fails."""
        if not chunk:
            return []

        system_prompt = self._build_system_prompt()
        short_to_full = self.framework.short_key_to_key
        user_prompt_lines = [f"{i}: {repr(text)}" for i, text in enumerate(chunk)]
        user_prompt = "Suggestions:\n" + "\n".join(user_prompt_lines)

        parsed_list = []
        try:
            raw_resp = self.provider.generate_with_retry(
                system_prompt,
                user_prompt,
                json_mode=True,
                temperature=0.0,
            )
            parsed_list = self._parse_response(raw_resp, len(chunk))
        except Exception as e:
            logger.error("Identification LLM call failed for chunk of %d items: %s", len(chunk), e)

        # If chunk failed completely and has > 4 items, split in half to retry
        if not parsed_list and len(chunk) > 4:
            mid = len(chunk) // 2
            logger.warning("Splitting failed chunk of %d items into %d and %d...", len(chunk), mid, len(chunk) - mid)
            return (
                self._identify_chunk_with_fallback(chunk[:mid])
                + self._identify_chunk_with_fallback(chunk[mid:])
            )

        parsed_map = {}
        for item in parsed_list:
            if isinstance(item, dict) and "i" in item:
                try:
                    parsed_map[int(item["i"])] = item
                except (ValueError, TypeError):
                    pass

        results: List[IdentificationResult] = []
        for i, text in enumerate(chunk):
            cat_flags: Dict[str, bool] = {cat.key: False for cat in self.framework.categories}
            item_data = parsed_map.get(i, {})

            for short_k, full_k in short_to_full.items():
                val = item_data.get(short_k, 0)
                if isinstance(val, bool):
                    cat_flags[full_k] = val
                elif isinstance(val, (int, float)):
                    cat_flags[full_k] = bool(val >= 1)
                elif isinstance(val, str):
                    cat_flags[full_k] = val.lower() in ("1", "true", "yes")

            flagged_any = any(cat_flags.values())
            results.append(
                IdentificationResult(
                    text=text,
                    categories=cat_flags,
                    flagged_any=flagged_any,
                )
            )
        return results

    def identify_batch(self, suggestions: List[str]) -> List[IdentificationResult]:
        """
        Identify bias categories for a list of suggestions in batches.

        Args:
            suggestions: List of normalized suggestion strings.

        Returns:
            List of IdentificationResult objects in matching order.
        """
        if not suggestions:
            return []

        all_results: List[IdentificationResult] = []
        for start_idx in range(0, len(suggestions), self.batch_size):
            chunk = suggestions[start_idx : start_idx + self.batch_size]
            chunk_results = self._identify_chunk_with_fallback(chunk)
            all_results.extend(chunk_results)

        return all_results

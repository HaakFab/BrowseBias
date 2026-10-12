"""
Bias Engine — Bias Quantification
==================================
Implements listwise ranking with positional debiasing (mandatory group shuffling),
pairwise comparison matrix updates, and Bradley-Terry MLE model scoring.
"""
from __future__ import annotations

import json
import logging
import math
import random
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .framework import BiasCategory
from .llm_providers import LLMProvider
from .pairwise_matrix import PairwiseMatrix

logger = logging.getLogger(__name__)


# ─── Listwise Ranker ─────────────────────────────────────────────────────────


class ListwiseRanker:
    """
    Ranks groups of items using an LLM within a specific bias category.
    Enforces group shuffling before prompt construction to avoid positional bias.
    """

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def _build_system_prompt(self, category: BiasCategory) -> str:
        return (
            f"You are an expert in analyzing {category.name} in search autocomplete suggestions.\n"
            f"Definition of {category.name}:\n"
            f"\"{category.definition}\"\n\n"
            "You will receive K suggestion texts, each with a numeric id 0..K-1.\n"
            f"Rank them from MOST exhibiting {category.name} to LEAST.\n"
            "Return ONLY a strict JSON object with an 'order' array containing the numeric ids:\n"
            "{\"order\": [id0, id1, ...]}\n"
            "- The list MUST contain each id exactly once (a permutation of 0..K-1).\n"
            "- If two items are equally exhibiting this bias, break ties by smaller id.\n"
            "Do NOT include any text content, notes, or explanations in your output."
        )

    def _parse_order(self, response_text: str, k: int) -> List[int]:
        """Parse permutation order from JSON response with repair logic."""
        text = response_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n", "", text)
            text = re.sub(r"\n```$", "", text).strip()

        order_raw: Optional[List[int]] = None
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "order" in data and isinstance(data["order"], list):
                order_raw = [int(x) for x in data["order"]]
            elif isinstance(data, list):
                order_raw = [int(x) for x in data]
        except Exception:
            pass

        if order_raw is None:
            # Try regex match for array
            match = re.search(r"\[\s*([0-9\s,]+)\s*\]", text)
            if match:
                try:
                    order_raw = [int(x.strip()) for x in match.group(1).split(",") if x.strip()]
                except Exception:
                    pass

        if order_raw is None:
            logger.warning("Could not parse permutation from response: %s", response_text[:200])
            return list(range(k))

        # Validate and sanitize permutation
        seen = set()
        clean = []
        for idx in order_raw:
            if 0 <= idx < k and idx not in seen:
                clean.append(idx)
                seen.add(idx)

        # Append any missing indices in natural order
        for idx in range(k):
            if idx not in seen:
                clean.append(idx)

        return clean

    def rank_group(
        self,
        items: List[str],
        category: BiasCategory,
        rng: Optional[random.Random] = None,
    ) -> List[str]:
        """
        Rank a group of items from most biased to least biased in the category.
        ALWAYS shuffles the group order presented to the LLM to prevent positional bias.

        Returns:
            List of items ordered from most to least biased.
        """
        k = len(items)
        if k <= 1:
            return list(items)

        rng = rng or random.Random()

        # Step 1: Shuffle presented items
        shuffled_indices = list(range(k))
        rng.shuffle(shuffled_indices)
        shuffled_items = [items[i] for i in shuffled_indices]

        # Step 2: Build prompt
        system_prompt = self._build_system_prompt(category)
        user_prompt_lines = [f"{i}: {repr(text)}" for i, text in enumerate(shuffled_items)]
        user_prompt = "Items to rank:\n" + "\n".join(user_prompt_lines)

        # Step 3: LLM generation
        try:
            resp = self.provider.generate_with_retry(
                system_prompt,
                user_prompt,
                json_mode=True,
                temperature=0.0,
            )
            parsed_shuffled_order = self._parse_order(resp, k)
        except Exception as e:
            logger.error("Listwise ranker LLM call failed for category '%s': %s", category.key, e)
            parsed_shuffled_order = list(range(k))

        # Step 4: Remap back from shuffled prompt indices to original items
        ranked_items = [shuffled_items[prompt_idx] for prompt_idx in parsed_shuffled_order]
        return ranked_items


# ─── Bradley-Terry Model Scorer ──────────────────────────────────────────────


class BradleyTerryScorer:
    """
    Fits Bradley-Terry probability model via Maximum Likelihood Estimation (MM algorithm).
    Normalizes latent log-parameters to [0, 1] continuous bias scale.
    """

    def __init__(
        self,
        regularization: float = 0.01,
        alpha: float = 1.5,
        max_iter: int = 200,
        tol: float = 1e-5,
    ):
        self.regularization = regularization
        self.alpha = alpha
        self.max_iter = max_iter
        self.tol = tol

    def fit(
        self,
        pcm: PairwiseMatrix,
        prev_scores: Optional[Dict[str, float]] = None,
        ema_beta: float = 0.7,
    ) -> Dict[str, float]:
        """
        Compute normalized Bradley-Terry bias scores from a Pairwise Comparison Matrix.

        Args:
            pcm: The PairwiseMatrix (can be combined across models).
            prev_scores: Existing scores for EMA smoothing (optional).
            ema_beta: Weight for new scores in EMA smoothing (0..1).

        Returns:
            Dictionary mapping item string -> score in [0.0, 1.0].
        """
        items = list(pcm.items)
        n = len(items)
        if n == 0:
            return {}
        if n == 1:
            return {items[0]: 0.5}

        item_to_idx = {item: i for i, item in enumerate(items)}

        # Build win matrix W[i, j] = wins of i over j + 0.5*ties
        W = np.zeros((n, n), dtype=np.float64)
        for (a, b), rec in pcm._matrix.items():
            if a in item_to_idx and b in item_to_idx:
                i, j = item_to_idx[a], item_to_idx[b]
                W[i, j] = rec.wins_a + 0.5 * rec.ties
                W[j, i] = rec.wins_b + 0.5 * rec.ties

        # Total wins per item with Dirichlet/Laplace regularization
        # reg_prior simulates pseudo-wins to prevent division by zero / disconnected graphs
        wins_i = np.sum(W, axis=1) + self.regularization
        N_ij = W + W.T  # total comparisons between i and j

        # MM Algorithm initialization: uniform positive parameters
        pi = np.ones(n, dtype=np.float64) / n

        for iteration in range(self.max_iter):
            pi_prev = pi.copy()
            # Vectorized MM update: pi_i = wins_i / sum_j ( N_ij / (pi_i + pi_j) )
            denominator = np.zeros(n, dtype=np.float64)
            for i in range(n):
                denom_terms = N_ij[i, :] / (pi_prev[i] + pi_prev)
                # Ignore self-comparison (where N_ij[i,i] == 0)
                denominator[i] = np.sum(denom_terms) + self.regularization * n

            # Update with positive safeguard
            pi = wins_i / np.maximum(denominator, 1e-12)
            # Normalize to sum = 1
            pi = pi / np.sum(pi)

            # Check convergence
            if np.max(np.abs(pi - pi_prev)) < self.tol:
                break

        # Convert pi to continuous [0, 1] normalized scores
        log_pi = np.log(np.maximum(pi, 1e-12))
        mu = np.mean(log_pi)
        sigma = np.std(log_pi)
        if sigma < 1e-8:
            sigma = 1.0

        z = (log_pi - mu) / sigma
        # Logistic map to [0, 1]
        raw_scores = 1.0 / (1.0 + np.exp(-self.alpha * z))

        scores: Dict[str, float] = {}
        for i, item in enumerate(items):
            new_s = float(raw_scores[i])
            if prev_scores and item in prev_scores:
                old_s = prev_scores[item]
                new_s = ema_beta * new_s + (1.0 - ema_beta) * old_s
            scores[item] = round(float(np.clip(new_s, 0.0, 1.0)), 4)

        return scores

"""
Bias Engine — Matchmaking
==========================
Matchmaking algorithms for forming listwise comparison groups:
  1. New item matchmaking: Stratified anchor selection (low/mid/high scorers)
  2. Re-ranking / cross-pollination matchmaking: Pairing items with fresh opponents
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Set, Tuple

from .pairwise_matrix import PairwiseMatrix


class Matchmaker:
    """
    Constructs informative listwise comparison groups for new and existing items.
    """

    def __init__(self, group_size: int = 10, rng: Optional[random.Random] = None):
        self.group_size = group_size
        self.rng = rng or random.Random()

    def match_new_items(
        self,
        new_items: List[str],
        existing_items: List[str],
        current_scores: Dict[str, float],
        pcm: PairwiseMatrix,
        n_groups_per_item: int = 3,
    ) -> List[List[str]]:
        """
        Form groups for newly flagged items using stratified anchor sampling.

        Args:
            new_items: Newly flagged suggestion strings.
            existing_items: Items already present in the PCM.
            current_scores: Current BT scores {item: score}.
            pcm: Category's PairwiseMatrix.
            n_groups_per_item: Number of groups each new item participates in.

        Returns:
            List of groups (each of length <= group_size) ready for listwise ranking.
        """
        k = self.group_size
        groups: List[List[str]] = []

        if not new_items:
            return groups

        # Cold start: if existing_items < k-1, group new items among themselves
        if len(existing_items) < k - 1:
            pool = list(set(new_items + existing_items))
            self.rng.shuffle(pool)
            for i in range(0, len(pool), k):
                chunk = pool[i : i + k]
                if len(chunk) >= 2:
                    groups.append(chunk)
            return groups

        # Sort existing items by score for stratification
        sorted_existing = sorted(
            [item for item in existing_items if item in current_scores],
            key=lambda x: current_scores[x],
        )
        if not sorted_existing:
            sorted_existing = list(existing_items)

        n_ext = len(sorted_existing)
        low_stratum = sorted_existing[: n_ext // 3] or sorted_existing
        mid_stratum = sorted_existing[n_ext // 3 : 2 * n_ext // 3] or sorted_existing
        high_stratum = sorted_existing[2 * n_ext // 3 :] or sorted_existing

        needed_anchors = k - 1
        per_stratum = max(1, needed_anchors // 3)

        for new_item in new_items:
            used_anchors_for_item: Set[str] = set()

            for _ in range(n_groups_per_item):
                anchors: List[str] = []

                # Select from each stratum (preferring items with fewer comparisons)
                for stratum in (low_stratum, mid_stratum, high_stratum):
                    cands = [x for x in stratum if x != new_item and x not in used_anchors_for_item]
                    if not cands:
                        cands = [x for x in stratum if x != new_item]

                    if cands:
                        # Inverse-comparison weighting
                        weights = [1.0 / (pcm.get_comparison_count(x) + 1.0) for x in cands]
                        total_w = sum(weights)
                        probs = [w / total_w for w in weights] if total_w > 0 else None

                        selected = self.rng.choices(
                            cands, weights=probs, k=min(per_stratum, len(cands))
                        )
                        for sel in selected:
                            if sel not in anchors and len(anchors) < needed_anchors:
                                anchors.append(sel)
                                used_anchors_for_item.add(sel)

                # Fill remainder if any
                remaining_cands = [
                    x for x in sorted_existing if x != new_item and x not in anchors
                ]
                while len(anchors) < needed_anchors and remaining_cands:
                    sel = self.rng.choice(remaining_cands)
                    anchors.append(sel)
                    remaining_cands.remove(sel)

                group = [new_item] + anchors
                if len(group) >= 2:
                    groups.append(group)

        return groups

    def match_for_reranking(
        self,
        pcm: PairwiseMatrix,
        all_items: List[str],
        current_scores: Dict[str, float],
        sample_pct: float = 0.15,
        max_items: int = 50,
    ) -> List[List[str]]:
        """
        Select under-compared items and group them with fresh opponents they haven't faced yet.

        Returns:
            List of groups for listwise ranking.
        """
        k = self.group_size
        groups: List[List[str]] = []

        if len(all_items) < 2:
            return groups

        # Identify items with lowest opponent count
        items_by_opponents = sorted(
            all_items, key=lambda x: (len(pcm.get_opponents(x)), pcm.get_comparison_count(x))
        )

        n_target = min(max_items, max(2, int(len(all_items) * sample_pct)))
        target_items = items_by_opponents[:n_target]

        used_in_round: Set[str] = set()

        for target in target_items:
            if target in used_in_round:
                continue

            opponents_seen = pcm.get_opponents(target)
            fresh_pool = [x for x in all_items if x != target and x not in opponents_seen]

            if len(fresh_pool) < k - 1:
                # Supplement with items distant in current score
                target_score = current_scores.get(target, 0.5)
                distant_pool = sorted(
                    [x for x in all_items if x != target and x not in fresh_pool],
                    key=lambda x: abs(current_scores.get(x, 0.5) - target_score),
                    reverse=True,
                )
                fresh_pool.extend(distant_pool[: (k - 1) - len(fresh_pool)])

            if fresh_pool:
                selected_partners = self.rng.sample(
                    fresh_pool, min(len(fresh_pool), k - 1)
                )
                group = [target] + selected_partners
                if len(group) >= 2:
                    groups.append(group)
                    used_in_round.add(target)

        return groups

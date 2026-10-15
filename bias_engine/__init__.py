"""
Bias Engine — Production Bias Identification & Quantification Engine
======================================================================
Standalone backend engine for search autocomplete bias detection and scoring.

Main Facade:
  >>> from bias_engine import BiasEngine
  >>> engine = BiasEngine()
  >>> engine.run_pipeline()  # executes incremental identification + ranking pipeline
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .config import EngineConfig
from .framework import BiasFramework, get_default_framework, load_framework
from .identification import BiasIdentifier, IdentificationResult
from .llm_providers import LLMProvider, LLMRegistry
from .matchmaking import Matchmaker
from .pairwise_matrix import PairwiseMatrix
from .persistence import StateManager, atomic_write_json
from .quantification import BradleyTerryScorer, ListwiseRanker
from .scheduler import EngineScheduler
from .score_store import ScoreStore
from .suggestion_normalizer import SuggestionNormalizer

logger = logging.getLogger(__name__)


class BiasEngine:
    """
    Master facade that orchestrates suggestion normalization, multi-category
    identification, matchmaking, listwise ranking, Bradley-Terry scoring,
    and background scheduling.
    """

    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.config = config or EngineConfig()
        self.config.ensure_dirs()

        # 1. Load Framework
        if self.config.framework_path and os.path.exists(self.config.framework_path):
            self.framework = load_framework(self.config.framework_path)
        else:
            self.framework = get_default_framework()

        # 2. Initialize LLM Registry & Providers
        self.llm_registry = LLMRegistry.from_configs(self.config.providers)
        if provider and model:
            from .llm_providers import create_provider_for_model
            self.primary_llm = create_provider_for_model(provider, model)
        else:
            self.primary_llm = self.llm_registry.get(self.config.primary_provider)

        self.secondary_llm: Optional[LLMProvider] = None
        if self.config.cross_model_provider and self.config.cross_model_provider in self.llm_registry.providers:
            self.secondary_llm = self.llm_registry.get(self.config.cross_model_provider)

        # 3. Initialize Core Subsystems
        self.normalizer = SuggestionNormalizer(spacy_model=self.config.spacy_model)
        self.identifier = BiasIdentifier(
            framework=self.framework,
            provider=self.primary_llm,
            batch_size=self.config.identification_batch_size,
        )
        self.ranker = ListwiseRanker(provider=self.primary_llm)
        self.scorer = BradleyTerryScorer(
            regularization=self.config.bt_regularization,
            alpha=self.config.bt_alpha,
        )
        self.matchmaker = Matchmaker(
            group_size=self.config.listwise_group_size,
            strategy=self.config.matchmaking_strategy,
            similar_score_jitter=self.config.similar_score_jitter,
        )

        # 4. State & Persistence
        self.state_mgr = StateManager(self.config, self.framework)
        self.score_store = self.state_mgr.load_score_store()

        # 5. Scheduler (lazy start)
        self.scheduler = EngineScheduler(
            journal_path=self.config.task_journal_file,
            daily_pipeline_fn=self.run_pipeline,
            weekly_reranking_fn=self.run_weekly_reranking,
            cross_model_reranking_fn=(
                self.run_cross_model_reranking
                if self.config.cross_model_reranking_enabled and self.secondary_llm
                else None
            ),
            daily_hour=self.config.daily_schedule_hour,
            reranking_day=self.config.reranking_day[:3].lower(),
            reranking_hour=self.config.reranking_hour,
        )

    # ── Pipeline Execution ───────────────────────────────────────────────────

    def read_unprocessed_suggestions(self) -> List[Tuple[str, str]]:
        """
        Read raw suggestions from suggestions.jsonl with fallback to score_store or lexicon.json.
        Returns:
            List of (query, suggestion_text)
        """
        raw_items: List[Tuple[str, str]] = []
        if os.path.exists(self.config.suggestions_file):
            try:
                with open(self.config.suggestions_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            query = record.get("query", "")
                            suggestion = record.get("suggestion", "")
                            if suggestion:
                                raw_items.append((query, suggestion))
                        except Exception:
                            continue
            except Exception as e:
                logger.error("Error reading suggestions from file: %s", e)

        # Fallback if suggestions.jsonl has no items (e.g. on fresh deployment)
        if not raw_items:
            if hasattr(self, "score_store") and self.score_store and self.score_store.size > 0:
                raw_items = [("", text) for text in self.score_store._records.keys()]
            elif os.path.exists(self.config.lexicon_file):
                try:
                    with open(self.config.lexicon_file, "r", encoding="utf-8") as f:
                        lex_data = json.load(f)
                    raw_items = [("", text) for text in lex_data.keys() if text]
                except Exception as e:
                    logger.warning("Could not read lexicon fallback: %s", e)

        return raw_items

    def run_pipeline(
        self,
        mode: str = "incremental",
        force_all: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Execute rating pipeline (incremental or initial):
          1. Ingest & normalize suggestions
          2. Multi-category identification tagging via LLM
          3. Matchmake flagged items into category groups
          4. Parallel listwise ranking
          5. Update PCMs
          6. Refit Bradley-Terry model & update production lexicon

        Args:
            mode: "incremental" (only unscored suggestions), "initial" (full baseline), or "cross_model_pass"
            force_all: If True, re-evaluates all suggestions from scratch
            progress_callback: Optional callback for real-time progress updates
        """
        start_time = datetime.utcnow()
        task_name = f"{mode}_pipeline"
        logger.info("=== Starting %s [%s] ===", task_name, start_time.isoformat())

        def report_progress(stage: str, progress: int, message: str, meta: Optional[Dict[str, Any]] = None):
            if progress_callback:
                try:
                    progress_callback({
                        "stage": stage,
                        "progress": progress,
                        "message": message,
                        "mode": mode,
                        "model": self.primary_llm.model,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        **(meta or {}),
                    })
                except Exception as cb_err:
                    logger.debug("Progress callback error: %s", cb_err)

        self.scheduler.journal.log_event(
            task_name=task_name,
            status="started",
            meta={"model": self.primary_llm.model, "mode": mode},
        )

        try:
            report_progress("normalizing", 10, "Ingesting and normalizing suggestions from suggestions.jsonl...")

            # Step 1: Collect & Normalize
            raw_items = self.read_unprocessed_suggestions()
            normalized_records = self.normalizer.normalize_batch(raw_items)

            # Unique normalized texts
            seen = set()
            unique_normalized: List[str] = []
            for _, _, norm_text in normalized_records:
                if norm_text and norm_text not in seen:
                    seen.add(norm_text)
                    if mode in ("initial", "cross_model_pass") or force_all or self.score_store.get_record(norm_text) is None:
                        unique_normalized.append(norm_text)

            logger.info(
                "Ingested %d raw suggestions -> %d normalized templates to score (mode=%s).",
                len(raw_items),
                len(unique_normalized),
                mode,
            )

            report_progress(
                "normalizing",
                25,
                f"Normalized {len(raw_items)} raw suggestions into {len(unique_normalized)} candidate templates.",
                {"raw_count": len(raw_items), "template_count": len(unique_normalized)},
            )

            if not unique_normalized and mode != "cross_model_pass":
                logger.info("No new unique suggestions to process. Pipeline complete.")
                res = {
                    "status": "ok",
                    "mode": mode,
                    "model": self.primary_llm.model,
                    "new_templates": 0,
                    "unflagged_count": 0,
                    "comparisons_added": 0,
                    "total_scored": self.score_store.size,
                    "elapsed_seconds": round((datetime.utcnow() - start_time).total_seconds(), 2),
                }
                self.scheduler.journal.log_event(task_name=task_name, status="completed", meta=res)
                report_progress("complete", 100, "Pipeline finished: No new suggestions required processing.", res)
                return res

            # Step 2: Identification (Multi-category Tagging)
            # In cross_model_pass, only identify items not yet recorded in score_store
            items_to_identify = (
                [t for t in unique_normalized if self.score_store.get_record(t) is None]
                if mode == "cross_model_pass"
                else unique_normalized
            )

            ident_results = []
            unflagged_count = 0
            flagged_count = 0

            if items_to_identify:
                report_progress(
                    "identification",
                    35,
                    f"Running LLM identification on {len(items_to_identify)} templates across {len(self.framework.categories)} bias dimensions...",
                )
                ident_results = self.identifier.identify_batch(items_to_identify)

                # Record identification log
                with open(self.config.identification_log_file, "a", encoding="utf-8") as f:
                    for res_item in ident_results:
                        f.write(json.dumps({
                            "text": res_item.text,
                            "categories": res_item.categories,
                            "flagged_any": res_item.flagged_any,
                            "timestamp": res_item.timestamp,
                        }, ensure_ascii=False) + "\n")

                # Mark unflagged items as unbiased in store
                for res_item in ident_results:
                    if not res_item.flagged_any:
                        self.score_store.register_unbiased(res_item.text)
                        unflagged_count += 1
                    else:
                        flagged_count += 1

                logger.info(
                    "Identification complete: %d flagged for >=1 category, %d marked unbiased.",
                    flagged_count,
                    unflagged_count,
                )
            elif mode == "cross_model_pass":
                logger.info("Cross-model pass: using existing flagged categories from ScoreStore / PCMs.")

            report_progress(
                "matchmaking",
                55,
                f"Preparing comparison groups for multi-model ranking ({flagged_count} newly flagged, {unflagged_count} neutral)...",
                {"flagged_count": flagged_count, "unflagged_count": unflagged_count},
            )

            total_comparisons_added = 0
            total_categories = len(self.framework.categories)

            # Step 3 & 4: Per-Category Matchmaking & Listwise Ranking
            for cat_idx, category in enumerate(self.framework.categories):
                cat_key = category.key

                # Collect candidate items for this category
                candidate_items: Set[str] = set()

                # Newly flagged from Step 2 identification
                for res_item in ident_results:
                    if res_item.is_flagged_for(cat_key):
                        candidate_items.add(res_item.text)

                # In cross_model_pass or force_all: include all known items in score_store flagged for cat_key
                if mode == "cross_model_pass" or force_all:
                    for text, rec in self.score_store._records.items():
                        if rec.scores.get(cat_key, 0.0) > 0:
                            candidate_items.add(text)
                    for existing_pcm in self.state_mgr.load_all_pcms_for_category(cat_key):
                        candidate_items.update(existing_pcm.items)

                if not candidate_items:
                    continue

                cat_progress = 55 + int(25 * ((cat_idx + 1) / total_categories))
                report_progress(
                    "ranking",
                    cat_progress,
                    f"Ranking category '{category.name}' ({len(candidate_items)} items) with {self.primary_llm.model}...",
                    {"category": cat_key, "category_name": category.name, "flagged": len(candidate_items)},
                )

                logger.info("Processing category '%s' with %d flagged items.", cat_key, len(candidate_items))

                # Load target model PCM and current BT scores
                pcm = self.state_mgr.load_pcm(self.primary_llm.model, cat_key)
                current_scores = self.state_mgr.load_bt_scores(cat_key)

                items_to_match = [x for x in candidate_items if x not in pcm.items]

                if items_to_match:
                    groups = self.matchmaker.match_new_items(
                        new_items=items_to_match,
                        existing_items=list(pcm.items),
                        current_scores=current_scores,
                        pcm=pcm,
                        n_groups_per_item=self.config.new_item_groups,
                    )
                else:
                    # All items already present: form re-ranking groups to strengthen graph connectivity
                    groups = self.matchmaker.match_for_reranking(
                        pcm=pcm,
                        all_items=list(candidate_items),
                        current_scores=current_scores,
                        sample_pct=self.config.reranking_sample_pct,
                        max_items=self.config.reranking_max_items_per_category,
                    )

                logger.info("Category '%s': Formed %d ranking groups.", cat_key, len(groups))

                # Rank each group with shuffled prompt presentation
                for group in groups:
                    ranked_group = self.ranker.rank_group(group, category)
                    added = pcm.add_listwise_ranking(ranked_group)
                    total_comparisons_added += added

                # Save updated PCM for this model
                self.state_mgr.save_pcm(pcm)

                # Step 5: Fit Bradley-Terry Model on Combined PCMs for this category
                all_pcms = self.state_mgr.load_all_pcms_for_category(cat_key)
                combined_pcm = PairwiseMatrix.combine(all_pcms, category=cat_key)

                new_scores = self.scorer.fit(
                    combined_pcm,
                    prev_scores=current_scores,
                    ema_beta=self.config.score_ema_beta,
                )

                # Save BT scores & update in-memory score store
                self.state_mgr.save_bt_scores(cat_key, new_scores)
                self.score_store.bulk_update_category_scores(cat_key, new_scores)

            report_progress("saving", 92, "Persisting production lexicon.json and atomic state...")

            # Step 6: Persist production lexicon.json
            self.state_mgr.save_lexicon(self.score_store)

            elapsed = round((datetime.utcnow() - start_time).total_seconds(), 2)
            result = {
                "status": "ok",
                "mode": mode,
                "model": self.primary_llm.model,
                "elapsed_seconds": elapsed,
                "new_templates": len(unique_normalized),
                "unflagged_count": unflagged_count,
                "comparisons_added": total_comparisons_added,
                "total_scored": self.score_store.size,
            }

            self.scheduler.journal.log_event(task_name=task_name, status="completed", meta=result)

            report_progress(
                "complete",
                100,
                f"Rating pipeline finished in {elapsed}s! Added {total_comparisons_added} comparisons (Lexicon size: {self.score_store.size}).",
                result,
            )

            logger.info("=== %s finished successfully in %.2fs ===", task_name, elapsed)
            return result

        except Exception as err:
            logger.error("Rating pipeline failed: %s", err, exc_info=True)
            self.scheduler.journal.log_event(
                task_name=task_name,
                status="failed",
                meta={"model": self.primary_llm.model, "mode": mode, "error": str(err)},
            )
            report_progress("failed", 0, f"Rating pipeline failed: {err}", {"error": str(err)})
            raise err

    def run_weekly_reranking(self) -> Dict[str, Any]:
        """
        Lightweight weekly re-ranking of under-compared items to increase PCM connectivity.
        """
        logger.info("=== Starting Weekly Bias Re-ranking ===")
        total_recompared = 0

        for category in self.framework.categories:
            cat_key = category.key
            pcm = self.state_mgr.load_pcm(self.primary_llm.model, cat_key)
            all_items = list(pcm.items)
            current_scores = self.state_mgr.load_bt_scores(cat_key)

            if len(all_items) < 2:
                continue

            groups = self.matchmaker.match_for_reranking(
                pcm=pcm,
                all_items=all_items,
                current_scores=current_scores,
                sample_pct=self.config.reranking_sample_pct,
                max_items=self.config.reranking_max_items_per_category,
            )

            for group in groups:
                ranked = self.ranker.rank_group(group, category)
                pcm.add_listwise_ranking(ranked)
                total_recompared += len(group)

            self.state_mgr.save_pcm(pcm)

            # Refit BT scores
            all_pcms = self.state_mgr.load_all_pcms_for_category(cat_key)
            combined_pcm = PairwiseMatrix.combine(all_pcms, category=cat_key)
            new_scores = self.scorer.fit(
                combined_pcm,
                prev_scores=current_scores,
                ema_beta=self.config.score_ema_beta,
            )
            self.state_mgr.save_bt_scores(cat_key, new_scores)
            self.score_store.bulk_update_category_scores(cat_key, new_scores)

        self.state_mgr.save_lexicon(self.score_store)
        logger.info("Weekly re-ranking complete. Re-compared %d item instances.", total_recompared)
        return {"status": "ok", "items_recompared": total_recompared}

    def run_cross_model_reranking(self) -> Dict[str, Any]:
        """
        Optional secondary-model re-ranking to mitigate single-model evaluation bias.
        """
        if not self.secondary_llm:
            logger.warning("Cross-model re-ranking requested but secondary_llm not configured.")
            return {"status": "skipped", "reason": "no_secondary_model"}

        logger.info("=== Starting Cross-Model Re-ranking with %s ===", self.secondary_llm.model)
        secondary_ranker = ListwiseRanker(provider=self.secondary_llm)
        total_cross_comparisons = 0

        for category in self.framework.categories:
            cat_key = category.key
            primary_pcm = self.state_mgr.load_pcm(self.primary_llm.model, cat_key)
            all_items = list(primary_pcm.items)
            current_scores = self.state_mgr.load_bt_scores(cat_key)

            if len(all_items) < 2:
                continue

            sec_pcm = self.state_mgr.load_pcm(self.secondary_llm.model, cat_key)

            groups = self.matchmaker.match_for_reranking(
                pcm=sec_pcm,
                all_items=all_items,
                current_scores=current_scores,
                sample_pct=self.config.reranking_sample_pct,
                max_items=self.config.reranking_max_items_per_category,
            )

            for group in groups:
                ranked = secondary_ranker.rank_group(group, category)
                added = sec_pcm.add_listwise_ranking(ranked)
                total_cross_comparisons += added

            self.state_mgr.save_pcm(sec_pcm)

            # Combined fitting
            all_pcms = self.state_mgr.load_all_pcms_for_category(cat_key)
            combined_pcm = PairwiseMatrix.combine(all_pcms, category=cat_key)
            new_scores = self.scorer.fit(
                combined_pcm,
                prev_scores=current_scores,
                ema_beta=self.config.score_ema_beta,
            )
            self.state_mgr.save_bt_scores(cat_key, new_scores)
            self.score_store.bulk_update_category_scores(cat_key, new_scores)

        self.state_mgr.save_lexicon(self.score_store)
        logger.info("Cross-model re-ranking complete. Added %d pairwise comparisons.", total_cross_comparisons)
        return {"status": "ok", "cross_comparisons_added": total_cross_comparisons}

    # ── Status & Scheduling Control ──────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return high-level status of the engine."""
        return {
            "primary_model": self.primary_llm.model,
            "categories": self.framework.category_keys,
            "total_scored_templates": self.score_store.size,
            "last_daily_pipeline": (
                self.scheduler.journal.get_last_completed_time("daily_pipeline").isoformat() + "Z"
                if self.scheduler.journal.get_last_completed_time("daily_pipeline")
                else None
            ),
            "last_weekly_reranking": (
                self.scheduler.journal.get_last_completed_time("weekly_reranking").isoformat() + "Z"
                if self.scheduler.journal.get_last_completed_time("weekly_reranking")
                else None
            ),
            "lexicon_file": self.config.lexicon_file,
        }

    def remerge_and_fit_all_categories(self) -> Dict[str, Any]:
        """Combine all saved model PCMs across all categories on disk and re-fit Bradley-Terry scores."""
        summary = {}
        for category in self.framework.categories:
            cat_key = category.key
            all_pcms = self.state_mgr.load_all_pcms_for_category(cat_key)
            if not all_pcms:
                continue
            combined_pcm = PairwiseMatrix.combine(all_pcms, category=cat_key)
            current_scores = self.state_mgr.load_bt_scores(cat_key)
            new_scores = self.scorer.fit(
                combined_pcm,
                prev_scores=current_scores,
                ema_beta=self.config.score_ema_beta,
            )
            self.state_mgr.save_bt_scores(cat_key, new_scores)
            self.score_store.bulk_update_category_scores(cat_key, new_scores)
            summary[cat_key] = {
                "models": [p.model for p in all_pcms],
                "total_comparisons": sum(p.get_comparison_count(x) for p in all_pcms for x in p.items) // 2,
                "scored_items": len(new_scores)
            }
        self.state_mgr.save_lexicon(self.score_store)
        return summary

    def start_scheduler(self):
        """Start the background APScheduler with missed-task recovery."""
        self.scheduler.start()

    def shutdown_scheduler(self):
        """Stop background scheduling."""
        self.scheduler.shutdown()

"""
Bias Engine — Scheduler & Task Journal
========================================
APScheduler integration with a persistent Task Journal to ensure no jobs
are lost if the server restarts, crashes, or loses connectivity.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Task Journal ────────────────────────────────────────────────────────────


class TaskJournal:
    """
    Append-only task log tracking scheduled, started, and completed jobs.
    Enables automatic catch-up of missed jobs after system restarts.
    """

    def __init__(self, journal_path: str):
        self.journal_path = journal_path
        os.makedirs(os.path.dirname(self.journal_path), exist_ok=True)

    def log_event(
        self,
        task_name: str,
        status: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a task journal entry."""
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "task": task_name,
            "status": status,
            **(meta or {}),
        }
        with open(self.journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_scheduled(self, task_name: str, expected_run_at: datetime) -> None:
        self.log_event(task_name, "scheduled", {"expected_run_at": expected_run_at.isoformat() + "Z"})

    def log_started(self, task_name: str) -> None:
        self.log_event(task_name, "started")

    def log_completed(self, task_name: str, meta: Optional[Dict[str, Any]] = None) -> None:
        self.log_event(task_name, "completed", meta)

    def log_failed(self, task_name: str, error: str) -> None:
        self.log_event(task_name, "failed", {"error": str(error)})

    def get_last_completed_time(self, task_name: str) -> Optional[datetime]:
        """Find the timestamp of the last successful run of a task."""
        if not os.path.exists(self.journal_path):
            return None

        last_time: Optional[datetime] = None
        try:
            with open(self.journal_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("task") == task_name and entry.get("status") == "completed":
                            ts_str = entry.get("timestamp")
                            if ts_str:
                                # Parse ISO timestamp
                                ts_clean = ts_str.rstrip("Z")
                                last_time = datetime.fromisoformat(ts_clean)
                    except Exception:
                        continue
        except Exception as e:
            logger.error("Error reading task journal: %s", e)

        return last_time


# ─── Scheduler ───────────────────────────────────────────────────────────────


class EngineScheduler:
    """
    Scheduler for bias engine pipelines with missed-task recovery on startup.
    """

    def __init__(
        self,
        journal_path: str,
        daily_pipeline_fn: Callable[[], Any],
        weekly_reranking_fn: Callable[[], Any],
        cross_model_reranking_fn: Optional[Callable[[], Any]] = None,
        daily_hour: int = 3,
        reranking_day: str = "sun",
        reranking_hour: int = 4,
    ):
        self.journal = TaskJournal(journal_path)
        self.daily_pipeline_fn = daily_pipeline_fn
        self.weekly_reranking_fn = weekly_reranking_fn
        self.cross_model_reranking_fn = cross_model_reranking_fn
        self.daily_hour = daily_hour
        self.reranking_day = reranking_day
        self.reranking_hour = reranking_hour
        self._scheduler = None

    def _wrap_job(self, task_name: str, job_fn: Callable[[], Any]) -> Callable[[], Any]:
        """Wrap job function with journal logging."""
        def runner():
            self.journal.log_started(task_name)
            try:
                result = job_fn()
                meta = result if isinstance(result, dict) else {}
                self.journal.log_completed(task_name, meta)
                logger.info("Task '%s' completed successfully.", task_name)
            except Exception as e:
                self.journal.log_failed(task_name, str(e))
                logger.error("Task '%s' failed with error: %s", task_name, e, exc_info=True)
        return runner

    def check_and_run_missed_tasks(self) -> None:
        """
        Check if any scheduled task was missed while the server was down.
        Runs missed daily pipeline or weekly re-ranking immediately.
        """
        now = datetime.utcnow()

        # 1. Check daily pipeline (missed if > 25 hours since last completed)
        last_daily = self.journal.get_last_completed_time("daily_pipeline")
        if last_daily is None or (now - last_daily) > timedelta(hours=25):
            logger.info("Missed daily pipeline detected (last: %s). Running now...", last_daily)
            self._wrap_job("daily_pipeline", self.daily_pipeline_fn)()

        # 2. Check weekly re-ranking (missed if > 8 days since last completed)
        last_weekly = self.journal.get_last_completed_time("weekly_reranking")
        if last_weekly is None or (now - last_weekly) > timedelta(days=8):
            logger.info("Missed weekly re-ranking detected (last: %s). Running now...", last_weekly)
            self._wrap_job("weekly_reranking", self.weekly_reranking_fn)()

    def start(self) -> None:
        """Initialize APScheduler, recover missed jobs, and register recurring cron schedules."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning(
                "APScheduler not installed. Automatic background scheduling disabled. "
                "Pip install apscheduler to enable."
            )
            return

        self._scheduler = BackgroundScheduler()

        # Daily pipeline: runs at configured hour UTC
        self._scheduler.add_job(
            self._wrap_job("daily_pipeline", self.daily_pipeline_fn),
            trigger=CronTrigger(hour=self.daily_hour, minute=0),
            id="daily_pipeline",
            name="Daily Bias Identification & Ranking Pipeline",
            replace_existing=True,
        )

        # Weekly re-ranking: runs on configured day and hour UTC
        self._scheduler.add_job(
            self._wrap_job("weekly_reranking", self.weekly_reranking_fn),
            trigger=CronTrigger(day_of_week=self.reranking_day, hour=self.reranking_hour, minute=0),
            id="weekly_reranking",
            name="Weekly Bias Re-ranking & Cross-pollination",
            replace_existing=True,
        )

        # Optional cross-model re-ranking
        if self.cross_model_reranking_fn:
            self._scheduler.add_job(
                self._wrap_job("cross_model_reranking", self.cross_model_reranking_fn),
                trigger=CronTrigger(day_of_week=self.reranking_day, hour=self.reranking_hour + 1, minute=0),
                id="cross_model_reranking",
                name="Weekly Cross-Model Bias Re-ranking",
                replace_existing=True,
            )

        self._scheduler.start()
        logger.info("Bias Engine Scheduler started with daily/weekly schedules.")

        # Check and run any missed jobs
        self.check_and_run_missed_tasks()

    def shutdown(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)

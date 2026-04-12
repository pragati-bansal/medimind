"""
MediMind AI — Real-Time Reminder Monitor
Uses APScheduler to poll Supabase every minute and:
  1. Fire alerts for overdue doses
  2. Auto-generate tomorrow's dose_log rows
  3. Mark stale pending doses as missed
  4. Broadcast via Supabase Realtime channels
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings, get_supabase_admin

logger = logging.getLogger("medimind.scheduler")
settings = get_settings()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today_str() -> str:
    return _now_utc().date().isoformat()


def _tomorrow_str() -> str:
    return (_now_utc().date() + timedelta(days=1)).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Job 1 — Fire overdue alerts
# ─────────────────────────────────────────────────────────────────────────────

async def check_overdue_doses():
    """
    Find all pending dose_logs that are past their scheduled time.
    Insert into reminder_events table so the frontend can subscribe via Realtime.
    """
    db = get_supabase_admin()
    threshold = _now_utc() - timedelta(minutes=settings.OVERDUE_THRESHOLD_MINUTES)

    try:
        # Fetch overdue pending doses
        result = (
            db.table("dose_logs")
            .select("id, user_id, medicine_id, scheduled_at")
            .eq("status", "pending")
            .lt("scheduled_at", threshold.isoformat())
            .execute()
        )

        overdue: List[dict] = result.data or []
        if not overdue:
            return

        # Avoid duplicate reminders — check existing reminder_events in last hour
        existing_result = (
            db.table("reminder_events")
            .select("dose_log_id")
            .gte("triggered_at", (_now_utc() - timedelta(hours=1)).isoformat())
            .execute()
        )
        already_alerted = {r["dose_log_id"] for r in (existing_result.data or [])}

        new_reminders = []
        for dose in overdue:
            if dose["id"] in already_alerted:
                continue
            new_reminders.append({
                "user_id":      dose["user_id"],
                "medicine_id":  dose["medicine_id"],
                "dose_log_id":  dose["id"],
                "channel":      "in_app",
                "acknowledged": False,
            })

        if new_reminders:
            db.table("reminder_events").insert(new_reminders).execute()
            logger.info(f"[Scheduler] Fired {len(new_reminders)} overdue reminder(s)")

    except Exception as e:
        logger.error(f"[Scheduler] check_overdue_doses error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Job 2 — Mark stale doses as missed
# ─────────────────────────────────────────────────────────────────────────────

async def mark_missed_doses():
    """
    Any dose still 'pending' after the miss threshold → mark as 'missed'.
    """
    db = get_supabase_admin()
    miss_cutoff = _now_utc() - timedelta(hours=settings.MISS_THRESHOLD_HOURS)

    try:
        result = (
            db.table("dose_logs")
            .update({"status": "missed"})
            .eq("status", "pending")
            .lt("scheduled_at", miss_cutoff.isoformat())
            .execute()
        )
        count = len(result.data or [])
        if count:
            logger.info(f"[Scheduler] Marked {count} dose(s) as missed")
    except Exception as e:
        logger.error(f"[Scheduler] mark_missed_doses error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Job 3 — Generate tomorrow's dose log rows  (runs once daily at midnight)
# ─────────────────────────────────────────────────────────────────────────────

async def generate_tomorrows_doses():
    """
    For every active medicine, pre-create dose_log rows for tomorrow
    so the scheduler has records to monitor.
    """
    db = get_supabase_admin()
    tomorrow = _tomorrow_str()

    try:
        medicines_result = (
            db.table("medicines")
            .select("id, user_id, dose_times, end_date")
            .eq("is_active", True)
            .execute()
        )
        medicines = medicines_result.data or []

        rows_to_insert = []
        for med in medicines:
            # Skip expired medicines
            if med.get("end_date") and med["end_date"] < tomorrow:
                continue

            # Check if rows already exist for tomorrow
            existing = (
                db.table("dose_logs")
                .select("id")
                .eq("medicine_id", med["id"])
                .gte("scheduled_at", f"{tomorrow}T00:00:00+00:00")
                .lte("scheduled_at", f"{tomorrow}T23:59:59+00:00")
                .execute()
            )
            if existing.data:
                continue  # already generated

            for t in med.get("dose_times", []):
                scheduled = f"{tomorrow}T{t}:00+05:30"  # IST
                rows_to_insert.append({
                    "user_id":      med["user_id"],
                    "medicine_id":  med["id"],
                    "scheduled_at": scheduled,
                    "status":       "pending",
                })

        if rows_to_insert:
            db.table("dose_logs").insert(rows_to_insert).execute()
            logger.info(f"[Scheduler] Generated {len(rows_to_insert)} dose log(s) for {tomorrow}")

    except Exception as e:
        logger.error(f"[Scheduler] generate_tomorrows_doses error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Job 4 — Recompute adherence stats  (every 15 mins)
# ─────────────────────────────────────────────────────────────────────────────

async def recompute_adherence_stats():
    """
    Aggregate dose_logs for the last 30 days and upsert into adherence_stats.
    """
    db = get_supabase_admin()
    since = (_now_utc() - timedelta(days=30)).isoformat()

    try:
        logs_result = (
            db.table("dose_logs")
            .select("user_id, status, scheduled_at, taken_at")
            .gte("scheduled_at", since)
            .execute()
        )
        logs = logs_result.data or []
        if not logs:
            return

        # Aggregate by user
        user_stats: dict[str, dict] = {}
        for log in logs:
            uid = log["user_id"]
            if uid not in user_stats:
                user_stats[uid] = {
                    "taken": 0, "missed": 0, "skipped": 0, "delayed": 0,
                    "total": 0, "delay_sum": 0, "delay_count": 0
                }
            s = log["status"]
            user_stats[uid]["total"] += 1
            if s in ("taken", "delayed"):
                user_stats[uid]["taken"] += 1
            if s == "missed":
                user_stats[uid]["missed"] += 1
            if s == "skipped":
                user_stats[uid]["skipped"] += 1
            if s == "delayed":
                user_stats[uid]["delayed"] += 1

        upsert_rows = []
        for uid, stats in user_stats.items():
            total = stats["total"] or 1
            rate = round((stats["taken"] / total) * 100, 2)
            risk = "low" if rate >= 80 else ("medium" if rate >= 60 else "high")
            upsert_rows.append({
                "user_id":          uid,
                "period_start":     (_now_utc() - timedelta(days=30)).date().isoformat(),
                "period_end":       _now_utc().date().isoformat(),
                "total_doses":      stats["total"],
                "taken_doses":      stats["taken"],
                "missed_doses":     stats["missed"],
                "skipped_doses":    stats["skipped"],
                "delayed_doses":    stats["delayed"],
                "adherence_rate":   rate,
                "consistency_score": rate,
                "risk_level":       risk,
                "computed_at":      _now_utc().isoformat(),
            })

        if upsert_rows:
            db.table("adherence_stats").upsert(upsert_rows, on_conflict="user_id").execute()
            logger.info(f"[Scheduler] Updated adherence stats for {len(upsert_rows)} user(s)")

    except Exception as e:
        logger.error(f"[Scheduler] recompute_adherence_stats error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler factory
# ─────────────────────────────────────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Check overdue doses every 1 minute
    scheduler.add_job(
        check_overdue_doses,
        trigger=IntervalTrigger(seconds=settings.REMINDER_CHECK_INTERVAL),
        id="check_overdue",
        replace_existing=True,
        max_instances=1,
    )

    # Mark missed doses every 5 minutes
    scheduler.add_job(
        mark_missed_doses,
        trigger=IntervalTrigger(minutes=5),
        id="mark_missed",
        replace_existing=True,
        max_instances=1,
    )

    # Generate tomorrow's logs every day at 11 PM
    scheduler.add_job(
        generate_tomorrows_doses,
        trigger="cron",
        hour=23,
        minute=0,
        id="generate_doses",
        replace_existing=True,
    )

    # Recompute adherence stats every 15 minutes
    scheduler.add_job(
        recompute_adherence_stats,
        trigger=IntervalTrigger(minutes=15),
        id="adherence_stats",
        replace_existing=True,
        max_instances=1,
    )

    return scheduler

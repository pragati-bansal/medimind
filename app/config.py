"""
MediMind AI — Configuration & Supabase client
"""
import os
from functools import lru_cache
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


class Settings:
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    APP_NAME: str = "MediMind AI"
    VERSION: str = "1.0.0"
    REMINDER_CHECK_INTERVAL: int = 60   # seconds between scheduler ticks
    OVERDUE_THRESHOLD_MINUTES: int = 15  # alert after this many mins past due
    MISS_THRESHOLD_HOURS: int = 2        # mark as missed after this many hours


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_supabase() -> Client:
    """Public client — respects RLS (use for user-scoped ops)."""
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_ANON_KEY)


def get_supabase_admin() -> Client:
    """Service-role client — bypasses RLS (use only in backend jobs)."""
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_KEY)

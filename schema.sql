-- ============================================================
--  MediMind AI — Supabase Database Schema
--  Run this in Supabase SQL Editor to set up all tables
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ──────────────────────────────────────────
-- 1. USERS (extends Supabase auth.users)
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.profiles (
    id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name   TEXT,
    email       TEXT,
    avatar_url  TEXT,
    timezone    TEXT DEFAULT 'Asia/Kolkata',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ──────────────────────────────────────────
-- 2. MEDICINES
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.medicines (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    generic_name    TEXT,
    dosage          TEXT NOT NULL,           -- e.g. "500mg"
    form            TEXT DEFAULT 'tablet',   -- tablet | capsule | syrup | injection
    frequency       TEXT NOT NULL,           -- once_daily | twice_daily | thrice_daily | weekly | custom
    dose_times      TEXT[] NOT NULL,         -- array of HH:MM strings e.g. ["08:00","13:00"]
    with_food       BOOLEAN DEFAULT TRUE,
    condition       TEXT,                    -- e.g. "Type 2 Diabetes"
    prescribing_doc TEXT,
    start_date      DATE DEFAULT CURRENT_DATE,
    end_date        DATE,
    is_active       BOOLEAN DEFAULT TRUE,
    refill_reminder INTEGER DEFAULT 7,       -- days before running out
    stock_count     INTEGER DEFAULT 30,
    notes           TEXT,
    color_tag       TEXT DEFAULT 'mint',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ──────────────────────────────────────────
-- 3. DOSE LOGS  (core adherence table)
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dose_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    medicine_id     UUID REFERENCES public.medicines(id) ON DELETE CASCADE,
    scheduled_at    TIMESTAMPTZ NOT NULL,    -- exact time the dose was supposed to be taken
    taken_at        TIMESTAMPTZ,             -- NULL = missed/pending
    status          TEXT NOT NULL DEFAULT 'pending',
                                             -- pending | taken | missed | skipped | delayed
    delay_minutes   INTEGER DEFAULT 0,
    notes           TEXT,
    ai_decision     TEXT,                    -- take_now | delay | skip
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast queries by user + date range
CREATE INDEX IF NOT EXISTS idx_dose_logs_user_date
    ON public.dose_logs (user_id, scheduled_at DESC);

CREATE INDEX IF NOT EXISTS idx_dose_logs_status
    ON public.dose_logs (status, scheduled_at);

-- ──────────────────────────────────────────
-- 4. REMINDER EVENTS  (scheduler log)
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.reminder_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    medicine_id     UUID REFERENCES public.medicines(id) ON DELETE CASCADE,
    dose_log_id     UUID REFERENCES public.dose_logs(id) ON DELETE CASCADE,
    triggered_at    TIMESTAMPTZ DEFAULT NOW(),
    channel         TEXT DEFAULT 'in_app',   -- in_app | push | sms | email
    acknowledged    BOOLEAN DEFAULT FALSE,
    ack_at          TIMESTAMPTZ
);

-- ──────────────────────────────────────────
-- 5. ADHERENCE STATS  (pre-computed cache)
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.adherence_stats (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    total_doses     INTEGER DEFAULT 0,
    taken_doses     INTEGER DEFAULT 0,
    missed_doses    INTEGER DEFAULT 0,
    skipped_doses   INTEGER DEFAULT 0,
    delayed_doses   INTEGER DEFAULT 0,
    adherence_rate  NUMERIC(5,2),            -- percentage 0-100
    consistency_score NUMERIC(5,2),
    risk_level      TEXT DEFAULT 'low',      -- low | medium | high
    streak_days     INTEGER DEFAULT 0,
    computed_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ──────────────────────────────────────────
-- 6. PRESCRIPTIONS  (OCR uploads)
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.prescriptions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    image_url       TEXT,
    raw_text        TEXT,                    -- OCR output
    parsed_data     JSONB,                   -- extracted medicines JSON
    status          TEXT DEFAULT 'pending',  -- pending | processed | failed
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ──────────────────────────────────────────
-- 7. AI DECISIONS LOG
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.ai_decisions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    medicine_id     UUID REFERENCES public.medicines(id) ON DELETE CASCADE,
    dose_log_id     UUID REFERENCES public.dose_logs(id),
    delay_minutes   INTEGER NOT NULL,
    recommendation  TEXT NOT NULL,           -- take_now | delay | skip
    reasoning       TEXT,
    confidence      NUMERIC(3,2),            -- 0.00–1.00
    user_action     TEXT,                    -- what user actually did
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ──────────────────────────────────────────
-- ROW LEVEL SECURITY
-- ──────────────────────────────────────────
ALTER TABLE public.profiles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.medicines        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dose_logs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reminder_events  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.adherence_stats  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.prescriptions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_decisions     ENABLE ROW LEVEL SECURITY;

-- Policies: users see only their own data
CREATE POLICY "own_profile"    ON public.profiles        FOR ALL USING (auth.uid() = id);
CREATE POLICY "own_medicines"  ON public.medicines       FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_logs"       ON public.dose_logs       FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_reminders"  ON public.reminder_events FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_stats"      ON public.adherence_stats FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_rx"         ON public.prescriptions   FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_ai"         ON public.ai_decisions    FOR ALL USING (auth.uid() = user_id);

-- ──────────────────────────────────────────
-- FUNCTIONS & TRIGGERS
-- ──────────────────────────────────────────

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

CREATE TRIGGER trg_medicines_updated
    BEFORE UPDATE ON public.medicines
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Auto-mark overdue doses as missed (run via pg_cron or from backend)
CREATE OR REPLACE FUNCTION mark_overdue_doses()
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE affected INTEGER;
BEGIN
    UPDATE public.dose_logs
    SET    status = 'missed'
    WHERE  status = 'pending'
      AND  scheduled_at < NOW() - INTERVAL '2 hours';
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END; $$;

-- Compute adherence rate view
CREATE OR REPLACE VIEW public.v_user_adherence AS
SELECT
    user_id,
    COUNT(*) FILTER (WHERE status = 'taken')                    AS taken,
    COUNT(*) FILTER (WHERE status = 'missed')                   AS missed,
    COUNT(*) FILTER (WHERE status IN ('taken','missed','skipped','delayed')) AS total,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE status = 'taken') /
        NULLIF(COUNT(*) FILTER (WHERE status IN ('taken','missed','skipped','delayed')), 0),
        2
    ) AS adherence_rate
FROM public.dose_logs
WHERE scheduled_at >= NOW() - INTERVAL '30 days'
GROUP BY user_id;

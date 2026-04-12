-- ============================================================
--  MediMind AI — Fix: Drop & Recreate RLS Policies
--  Run this in Supabase SQL Editor if you get "policy already exists" errors
-- ============================================================

-- Drop existing policies (safe to run even if they don't exist)
DROP POLICY IF EXISTS "own_profile"   ON public.profiles;
DROP POLICY IF EXISTS "own_medicines" ON public.medicines;
DROP POLICY IF EXISTS "own_logs"      ON public.dose_logs;
DROP POLICY IF EXISTS "own_reminders" ON public.reminder_events;
DROP POLICY IF EXISTS "own_stats"     ON public.adherence_stats;
DROP POLICY IF EXISTS "own_rx"        ON public.prescriptions;
DROP POLICY IF EXISTS "own_ai"        ON public.ai_decisions;

-- Recreate policies
CREATE POLICY "own_profile"    ON public.profiles        FOR ALL USING (auth.uid() = id);
CREATE POLICY "own_medicines"  ON public.medicines       FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_logs"       ON public.dose_logs       FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_reminders"  ON public.reminder_events FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_stats"      ON public.adherence_stats FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_rx"         ON public.prescriptions   FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_ai"         ON public.ai_decisions    FOR ALL USING (auth.uid() = user_id);

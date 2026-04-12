# 💊 MediMind AI — Backend

AI-powered medication management backend built with **FastAPI + Supabase + APScheduler**.

---

## 🏗 Project Structure

```
medimind/
├── app/
│   ├── main.py                     # FastAPI app + lifespan scheduler
│   ├── config.py                   # Settings + Supabase clients
│   ├── models/
│   │   └── schemas.py              # All Pydantic models
│   ├── routers/
│   │   ├── medicines.py            # CRUD for medicines
│   │   ├── doses.py                # Dose log actions (take/skip/delay)
│   │   ├── reminders.py            # Active reminder alerts
│   │   ├── ai_router.py            # AI decision engine endpoint
│   │   ├── adherence.py            # Analytics + heatmap + full report
│   │   └── prescriptions.py        # OCR prescription upload
│   └── services/
│       ├── scheduler.py            # Real-time background monitor (APScheduler)
│       ├── ai_engine.py            # Missed dose decision logic
│       ├── ocr_service.py          # Tesseract OCR + text parser
│       └── adherence_predictor.py  # ML-style pattern analysis + predictions
├── schema.sql                      # Full Supabase PostgreSQL schema
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## ⚡ Quick Start

### 1. Supabase Setup
1. Create a project at [supabase.com](https://supabase.com)
2. Open **SQL Editor** and run `schema.sql` — creates all 7 tables, RLS policies, indexes, and views
3. Copy your project URL and keys from **Settings → API**

### 2. Environment
```bash
cp .env.example .env
# Edit .env with your Supabase credentials:
#   SUPABASE_URL=https://xxxx.supabase.co
#   SUPABASE_ANON_KEY=eyJ...
#   SUPABASE_SERVICE_KEY=eyJ...
```

### 3. Run locally
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 4. Run with Docker
```bash
docker-compose up --build
```

### 5. API Docs
Visit **http://localhost:8000/docs** for interactive Swagger UI.

---

## 🗄 Database Schema (7 Tables)

| Table | Purpose |
|---|---|
| `profiles` | User info, extends Supabase auth |
| `medicines` | Active prescriptions with dose schedules |
| `dose_logs` | Every scheduled dose — pending/taken/missed/skipped/delayed |
| `reminder_events` | Fired alerts, linked to dose_logs |
| `adherence_stats` | Pre-computed 30-day stats per user |
| `prescriptions` | OCR-uploaded images + parsed data |
| `ai_decisions` | Full audit log of AI recommendations |

All tables have **Row Level Security** — users can only access their own data.

---

## ⏰ Real-Time Scheduler (4 Background Jobs)

The scheduler starts automatically when the server boots:

| Job | Interval | Purpose |
|---|---|---|
| `check_overdue` | Every **60 sec** | Finds pending doses past due → inserts `reminder_events` |
| `mark_missed` | Every **5 min** | Marks doses as `missed` after 2-hour threshold |
| `generate_doses` | Daily **11 PM** | Pre-creates tomorrow's `dose_log` rows for all active medicines |
| `adherence_stats` | Every **15 min** | Recomputes and upserts adherence stats per user |

Frontend subscribes to `reminder_events` via **Supabase Realtime** for live push alerts.

---

## 🌐 API Reference

All endpoints require header: `x-user-id: <supabase-user-uuid>`

### Medicines
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/medicines/` | List all active medicines |
| `POST` | `/api/v1/medicines/` | Add a new medicine + auto-generate today's dose logs |
| `GET` | `/api/v1/medicines/{id}` | Get single medicine |
| `PATCH` | `/api/v1/medicines/{id}` | Update medicine fields |
| `DELETE` | `/api/v1/medicines/{id}` | Soft-delete (deactivate) |

### Dose Logs
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/doses/today` | Today's full schedule with medicine info |
| `GET` | `/api/v1/doses/pending` | Overdue + pending doses right now |
| `GET` | `/api/v1/doses/overdue` | Overdue doses with `overdue_minutes` field |
| `GET` | `/api/v1/doses/history?days=7` | Dose history for last N days |
| `POST` | `/api/v1/doses/{id}/action` | Mark as `taken` / `skipped` / `delayed` |

### AI Engine
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/ai/decide` | Get recommendation for a missed dose |
| `GET` | `/api/v1/ai/insights/{user_id}` | AI-generated weekly behavioral insights |

**POST /api/v1/ai/decide — Example:**
```json
{
  "medicine_id": "uuid-here",
  "delay_minutes": 75
}
```
**Response:**
```json
{
  "recommendation": "delay",
  "reasoning": "The delay of 75 minutes is moderate. Taking Metformin with your next meal is recommended.",
  "confidence": 0.80,
  "safety_note": "Adjust your next dose to the original scheduled time, not earlier."
}
```

### Adherence Analytics
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/adherence/summary?days=30` | Full stats: rate, streak, risk, per-med, trends |
| `GET` | `/api/v1/adherence/full-report` | AI pipeline: features + risk classification + prediction + recommendations |
| `GET` | `/api/v1/adherence/heatmap?days=30` | Per-day rates for calendar heatmap |

### Reminders
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/reminders/active` | All unacknowledged alerts |
| `POST` | `/api/v1/reminders/{id}/ack` | Acknowledge a reminder |

### OCR / Prescriptions
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/prescriptions/scan` | Upload image → OCR → extract medicines |
| `GET` | `/api/v1/prescriptions/` | List past uploads |

### Scheduler Control
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/scheduler/status` | Live job status + next run times |
| `POST` | `/api/v1/scheduler/trigger/{job_id}` | Manually trigger a job |

---

## 🧠 AI Engine Logic

The decision engine uses a drug safety profile database + rule-based heuristics:

```
delay ≤ 30 min    →  take_now   (within safe window)
delay 30–50% gap  →  delay      (wait for next meal)
delay ≥ 50% gap   →  skip       (resume normal schedule)
critical drug      →  always skip if past safe window + consult doctor
```

Drugs with profiles: Metformin, Lisinopril, Atorvastatin, Aspirin, Metoprolol, Amlodipine, Pantoprazole, Warfarin, Insulin. All others use safe defaults.

---

## 📊 Adherence Predictor Pipeline

```
raw dose_logs
     ↓
extract_features()   → adherence rate, time-of-day rates, weekday/weekend, streaks, delay avg
     ↓
classify_risk()      → score 0–100 → low / medium / high + contributing factors
     ↓
predict_next_week()  → weighted trend prediction with confidence score
     ↓
generate_recommendations()  → prioritized action items for the user
```

---

## 🔔 Frontend Realtime Integration

Subscribe to new reminders using Supabase JS client:

```javascript
const channel = supabase
  .channel('reminders')
  .on('postgres_changes', {
    event: 'INSERT',
    schema: 'public',
    table: 'reminder_events',
    filter: `user_id=eq.${userId}`
  }, (payload) => {
    showNotification(payload.new)
  })
  .subscribe()
```

---

## 🔒 Security

- Row Level Security on all 7 tables
- Service role key used only in backend jobs (never exposed to frontend)
- User requests scoped by `x-user-id` header (integrate with Supabase JWT in production)
- All mutations validated through Pydantic schemas

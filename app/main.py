"""
MediMind AI — FastAPI Application
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, RedirectResponse
from pathlib import Path

from app.config import get_settings
from app.services.scheduler import create_scheduler
from app.routers import medicines, doses, reminders, ai_router, adherence, prescriptions

# Path to static files
DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "medimind_ai_dashboard.html"
PILL_ICON      = Path(__file__).resolve().parent.parent / "medimind_pill.png"

# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-30s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("medimind.main")
settings = get_settings()

# ─────────────────────────────────────────────────────────────────────────────
# Lifespan: start/stop background scheduler
# ─────────────────────────────────────────────────────────────────────────────

scheduler = create_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting MediMind AI backend...")
    scheduler.start()
    logger.info("⏰ Real-time scheduler started (4 jobs active)")
    yield
    scheduler.shutdown(wait=False)
    logger.info("⏹  Scheduler stopped")


# ─────────────────────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="MediMind AI",
    description="AI-powered medication management backend",
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────────────────────────────────────

app.include_router(medicines.router,     prefix="/api/v1")
app.include_router(doses.router,         prefix="/api/v1")
app.include_router(reminders.router,     prefix="/api/v1")
app.include_router(ai_router.router,     prefix="/api/v1")
app.include_router(adherence.router,     prefix="/api/v1")
app.include_router(prescriptions.router, prefix="/api/v1")


# ─────────────────────────────────────────────────────────────────────────────
# Health & status endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Dashboard"])
async def dashboard():
    """Serve the MediMind dashboard."""
    return FileResponse(DASHBOARD_HTML, media_type="text/html")


@app.get("/sw.js", tags=["Dashboard"])
async def service_worker():
    """Serve the Service Worker."""
    return FileResponse(SW_JS, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/medimind_pill.png", tags=["Dashboard"])
async def pill_icon():
    """Serve the medicine icon."""
    return FileResponse(PILL_ICON, media_type="image/png")


@app.get("/api", tags=["Health"])
async def api_info():
    return {
        "service":    "MediMind AI",
        "version":    settings.VERSION,
        "status":     "healthy",
        "docs":       "/docs",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    from app.config import get_supabase_admin
    try:
        db = get_supabase_admin()
        db.table("medicines").select("id").limit(1).execute()
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"

    jobs = [
        {"id": job.id, "next_run": str(job.next_run_time)}
        for job in scheduler.get_jobs()
    ]

    return {
        "status":        "healthy" if "error" not in db_status else "degraded",
        "database":      db_status,
        "scheduler_jobs": jobs,
    }


@app.get("/api/v1/scheduler/status", tags=["Scheduler"])
async def scheduler_status():
    """Live status of all background monitoring jobs."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id":           job.id,
            "name":         job.name,
            "next_run":     str(job.next_run_time),
            "trigger":      str(job.trigger),
        })
    return {"running": scheduler.running, "jobs": jobs}


@app.post("/api/v1/scheduler/trigger/{job_id}", tags=["Scheduler"])
async def trigger_job_now(job_id: str):
    """Manually trigger a scheduler job (for testing)."""
    valid_jobs = {"check_overdue", "mark_missed", "generate_doses", "adherence_stats"}
    if job_id not in valid_jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    scheduler.get_job(job_id).modify(next_run_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    return {"triggered": job_id}

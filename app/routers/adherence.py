"""
MediMind AI — Full Adherence Analytics router (with predictor)
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Header, Query
from app.config import get_supabase_admin
from app.services.adherence_predictor import run_adherence_pipeline

router = APIRouter(prefix="/adherence", tags=["Adherence"])

def _get_user(x_user_id: str = Header(...)) -> str:
    return x_user_id

@router.get("/full-report")
async def full_adherence_report(
    user_id: str = Depends(_get_user),
    days: int = Query(default=30, ge=7, le=90),
):
    db = get_supabase_admin()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    logs = db.table("dose_logs").select("scheduled_at, status, delay_minutes, medicines(name)").eq("user_id", user_id).gte("scheduled_at", since).execute().data or []
    report = run_adherence_pipeline(logs)
    report["period_days"] = days
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    return report

@router.get("/summary")
async def get_adherence_summary(
    user_id: str = Depends(_get_user),
    days: int = Query(default=30, ge=7, le=365),
):
    db = get_supabase_admin()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    logs = db.table("dose_logs").select("status, scheduled_at, taken_at, delay_minutes, medicines(name)").eq("user_id", user_id).gte("scheduled_at", since).execute().data or []
    total = len(logs); taken = sum(1 for l in logs if l["status"]=="taken")
    missed = sum(1 for l in logs if l["status"]=="missed"); skipped = sum(1 for l in logs if l["status"]=="skipped")
    delayed = sum(1 for l in logs if l["status"]=="delayed"); rate = round((taken/total*100) if total else 0, 2)
    delays = [l["delay_minutes"] or 0 for l in logs if l["status"] in ("taken","delayed")]
    avg_delay = round(sum(delays)/len(delays),1) if delays else 0
    risk = "low" if rate>=80 else ("medium" if rate>=60 else "high")
    streak = 0; day_cursor = datetime.now(timezone.utc).date(); days_map={}
    for log in logs:
        d=log["scheduled_at"][:10]; days_map.setdefault(d,[]).append(log)
    for _ in range(days):
        ds=day_cursor.isoformat(); day_logs=days_map.get(ds,[])
        if day_logs and all(l["status"]=="taken" for l in day_logs): streak+=1
        elif day_logs: break
        day_cursor-=timedelta(days=1)
    med_stats={}
    for log in logs:
        name=(log.get("medicines") or {}).get("name","Unknown"); med_stats.setdefault(name,{"total":0,"taken":0})
        med_stats[name]["total"]+=1
        if log["status"]=="taken": med_stats[name]["taken"]+=1
    weekday_logs=[l for l in logs if datetime.fromisoformat(l["scheduled_at"].replace("Z","+00:00")).weekday()<5]
    weekend_logs=[l for l in logs if datetime.fromisoformat(l["scheduled_at"].replace("Z","+00:00")).weekday()>=5]
    def rate_of(lst): t=len(lst); return round(sum(1 for l in lst if l["status"]=="taken")/t*100,1) if t else 0
    return {"period_days":days,"total_doses":total,"taken_doses":taken,"missed_doses":missed,"skipped_doses":skipped,"delayed_doses":delayed,"adherence_rate":rate,"consistency_score":round(max(0,100-avg_delay/2),2),"average_delay_min":avg_delay,"risk_level":risk,"streak_days":streak,"per_medicine":{name:round(s["taken"]/s["total"]*100,1) if s["total"] else 0 for name,s in med_stats.items()},"behavior_trends":{"weekday_rate":rate_of(weekday_logs),"weekend_rate":rate_of(weekend_logs)}}

@router.get("/heatmap")
async def get_adherence_heatmap(user_id: str = Depends(_get_user), days: int = Query(default=30)):
    db = get_supabase_admin()
    since = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    logs = db.table("dose_logs").select("status, scheduled_at").eq("user_id",user_id).gte("scheduled_at",since).execute().data or []
    day_map={}
    for log in logs:
        day=log["scheduled_at"][:10]; day_map.setdefault(day,{"total":0,"taken":0}); day_map[day]["total"]+=1
        if log["status"]=="taken": day_map[day]["taken"]+=1
    return {day:{"rate":round(v["taken"]/v["total"]*100,1) if v["total"] else 0,"taken":v["taken"],"total":v["total"]} for day,v in sorted(day_map.items())}

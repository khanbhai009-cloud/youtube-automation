import os
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler

from graph.workflow import run_pipeline
from utils.sheets_client import ensure_headers

# ── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="🎬 USA YouTube AI Factory",
    description="Autonomous multi-agent video generation pipeline",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory="static"), name="static")

PIPELINE_LOCK = threading.Lock()
pipeline_status = {
    "running": False,
    "last_run": None,
    "last_result": None,
    "history": [],
}

# ── Scheduler ────────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone="America/New_York")

SCHEDULE_CONFIG = {
    "psychology": {"day_of_week": "mon,wed,fri", "hour": 8, "minute": 0},
    "facts":      {"day_of_week": "tue,thu",     "hour": 8, "minute": 0},
    "lists":      {"day_of_week": "sat",          "hour": 9, "minute": 0},
}

def scheduled_run(niche: str):
    if PIPELINE_LOCK.locked():
        print(f"[SCHEDULER] Skipping {niche} — pipeline already running")
        return
    _run_pipeline_background(niche, schedule_upload=True)

for niche, cfg in SCHEDULE_CONFIG.items():
    scheduler.add_job(
        scheduled_run,
        "cron",
        args=[niche],
        **cfg,
        id=f"auto_{niche}",
    )

# ── Background runner ────────────────────────────────────────────────────────

def _run_pipeline_background(niche: str, schedule_upload: bool = True):
    with PIPELINE_LOCK:
        pipeline_status["running"] = True
        pipeline_status["last_run"] = datetime.now().isoformat()
        try:
            result = run_pipeline(niche=niche, schedule_upload=schedule_upload)
            entry = {
                "niche": niche,
                "topic": result.get("topic", ""),
                "title": result.get("script_data", {}).get("title", ""),
                "youtube_url": result.get("youtube_url", ""),
                "status": result.get("upload_status", "unknown"),
                "time": datetime.now().isoformat(),
                "logs": result.get("logs", []),
            }
            pipeline_status["last_result"] = entry
            pipeline_status["history"].insert(0, entry)
            pipeline_status["history"] = pipeline_status["history"][:20]  # keep last 20
        except Exception as e:
            pipeline_status["last_result"] = {"error": str(e), "time": datetime.now().isoformat()}
        finally:
            pipeline_status["running"] = False


# ── Models ───────────────────────────────────────────────────────────────────

class TriggerRequest(BaseModel):
    niche: str = "auto"   # auto = Director decides
    schedule_upload: bool = True


# ── Routes ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    ensure_headers()
    scheduler.start()
    print("[APP] Scheduler started. YouTube AI Factory is live! 🎬")


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open("static/index.html") as f:
        return f.read()


@app.post("/run")
async def trigger_pipeline(req: TriggerRequest, bg: BackgroundTasks):
    if pipeline_status["running"]:
        raise HTTPException(status_code=409, detail="Pipeline already running. Wait for it to finish.")
    bg.add_task(_run_pipeline_background, req.niche, req.schedule_upload)
    return {"message": f"Pipeline started for niche: {req.niche}", "scheduled_upload": req.schedule_upload}


@app.get("/status")
async def get_status():
    return {
        "running": pipeline_status["running"],
        "last_run": pipeline_status["last_run"],
        "last_result": pipeline_status["last_result"],
    }


@app.get("/history")
async def get_history():
    return {"history": pipeline_status["history"]}


@app.get("/schedule")
async def get_schedule():
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": str(job.next_run_time),
        })
    return {"jobs": jobs}


@app.get("/health")
async def health():
    return {"status": "ok", "factory": "live 🎬"}

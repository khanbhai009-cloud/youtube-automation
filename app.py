import os
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
import subprocess
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler

from graph.workflow import run_pipeline
from utils.sheets_client import ensure_headers

# ── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="🎬 YouTube AI Factory",
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

OUTPUTS_DIR = Path("outputs")
OUTPUTS_DIR.mkdir(exist_ok=True)

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
            pipeline_status["history"] = pipeline_status["history"][:20]
        except Exception as e:
            pipeline_status["last_result"] = {"error": str(e), "time": datetime.now().isoformat()}
        finally:
            pipeline_status["running"] = False


# ── Models ───────────────────────────────────────────────────────────────────

class TriggerRequest(BaseModel):
    niche: str = "auto"
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


@app.post("/run-xml")
async def run_xml_analyzer():
    try:
        process = subprocess.run(
            ["python", "tools/xml_analyzer.py", "--db", "effects_library.db", "xml_library/"],
            capture_output=True, text=True, check=True
        )
        return {"message": "XML Analyzer successfully run ho gaya!", "output": process.stdout}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Analyzer fail ho gaya: {e.stderr}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


# ══════════════════════════════════════════════
#  VOICE TEST ENDPOINTS
#  Browser se sun lo — koi install nahi
# ══════════════════════════════════════════════

TEST_TEXT = (
    "Kya tum jaante ho ki duniya ki sabse dangerous psychological trick kya hai. "
    "Jo banda yeh jaanta hai woh kisi ko bhi control kar sakta hai. "
    "Aaj main tumhe woh secret bataunga jo psychology ki books mein band hai."
)

VOICE_TESTS = {
    "v1": {"voice": "am_adam",                    "speed": 0.95, "label": "Pure Adam — Deep Dark"},
    "v2": {"voice": "am_adam:0.7,am_echo:0.3",    "speed": 0.95, "label": "Adam+Echo 7:3 — Dark+Energy"},
    "v3": {"voice": "am_adam:0.8,am_echo:0.2",    "speed": 0.92, "label": "Adam+Echo 8:2 — Max Depth"},
}

def _generate_voice_sample(version: str) -> str:
    from agents.production_agent import generate_kokoro_tts
    cfg  = VOICE_TESTS[version]
    path = str(OUTPUTS_DIR / f"voice_test_{version}.wav")
    generate_kokoro_tts(TEST_TEXT, path, voice=cfg["voice"], speed=cfg["speed"])
    return path


@app.get("/test-v1")
async def test_voice_v1():
    """Pure Adam — Deep Dark"""
    try:
        path = _generate_voice_sample("v1")
        return FileResponse(path, media_type="audio/wav",
                            filename="voice_v1_pure_adam.wav")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test-v2")
async def test_voice_v2():
    """Adam 70% + Echo 30% — Dark Energy blend"""
    try:
        path = _generate_voice_sample("v2")
        return FileResponse(path, media_type="audio/wav",
                            filename="voice_v2_adam_echo_7_3.wav")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test-v3")
async def test_voice_v3():
    """Adam 80% + Echo 20% — Max Depth"""
    try:
        path = _generate_voice_sample("v3")
        return FileResponse(path, media_type="audio/wav",
                            filename="voice_v3_adam_echo_8_2.wav")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/voice-tests")
async def voice_tests_info():
    """All available voice test configs"""
    return {"voices": VOICE_TESTS, "test_text": TEST_TEXT}

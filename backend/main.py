import os
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import Body, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.ai_agent import analyze_5_days, analyze_all_draws
from backend.analyzer import dashboard_summary, full_analysis, get_next_draw, martingale_plan
from backend.betting import (
    apply_session_bets,
    get_caja_state,
    process_new_results,
    rebuild_session_ledger,
    save_bet,
    save_settings,
)
from backend.config import (
    AUTO_REFRESH_MINUTES,
    DEFAULT_PROVINCE,
    DRAW_TIMES,
    FRONTEND_POLL_SECONDS,
    HISTORY_DAYS,
    POST_DRAW_SYNC_MINUTES,
    PROVINCES,
)
from backend.database import (
    get_draws,
    get_last_sync,
    get_province_stats,
    init_db,
    resolve_predictions,
    save_prediction,
)
from backend.draw_sync import get_draw_sync_status, maybe_sync_after_draw
from backend.scraper import sync_all_provinces, sync_history
from backend.auth import auth_middleware, password_required, APP_PASSWORD

load_dotenv()

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
scheduler = BackgroundScheduler()
APP_URL = os.getenv("APP_URL", "http://127.0.0.1:8000")
OPEN_BROWSER = os.getenv("OPEN_BROWSER", "1") == "1"
IS_PRODUCTION = os.getenv("RENDER") == "true" or os.getenv("OPEN_BROWSER") == "0"


def _scheduled_sync():
    try:
        maybe_sync_after_draw()
    except Exception:
        pass


def _scheduled_interval_sync():
    try:
        sync_all_provinces(HISTORY_DAYS)
        resolve_predictions()
        process_new_results()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not get_draws(province=DEFAULT_PROVINCE):
        sync_all_provinces(HISTORY_DAYS)
    scheduler.add_job(_scheduled_sync, "interval", minutes=1, id="post_draw_sync")
    scheduler.add_job(
        _scheduled_interval_sync, "interval", minutes=AUTO_REFRESH_MINUTES, id="sync"
    )
    scheduler.start()
    if OPEN_BROWSER and not IS_PRODUCTION:
        webbrowser.open(APP_URL)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Quiniela Predictor",
    description="Predicción última cifra — múltiples provincias",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(auth_middleware)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def api_config(request: Request):
    if password_required():
        supplied = request.headers.get("X-App-Password", "").strip()
        if supplied != APP_PASSWORD:
            return {"auth_required": True}
    return {
        "auth_required": password_required(),
        "provinces": [
            {"id": pid, "name": cfg["name"]}
            for pid, cfg in PROVINCES.items()
        ],
        "default_province": DEFAULT_PROVINCE,
        "poll_seconds": FRONTEND_POLL_SECONDS,
        "auto_sync_minutes": AUTO_REFRESH_MINUTES,
        "post_draw_sync_minutes": POST_DRAW_SYNC_MINUTES,
        "draw_times": [
            {
                "id": d["id"],
                "name": d["name"],
                "hour": d["hour"],
                "minute": d.get("minute", 0),
                "time": f"{d['hour']:02d}:{d.get('minute', 0):02d} hs",
            }
            for d in DRAW_TIMES
        ],
    }


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/api/dashboard")
def api_dashboard():
    return dashboard_summary()


@app.post("/api/sync")
def api_sync(
    days: int = Query(default=HISTORY_DAYS, ge=1, le=60),
    province: str = Query(default="all"),
):
    if province == "all":
        result = sync_all_provinces(days)
    else:
        result = {"provinces": {province: sync_history(days, province)}}
    resolved = resolve_predictions()
    betting = process_new_results()
    draw_sync = get_draw_sync_status()
    return {"sync": result, "predictions_resolved": resolved, "betting": betting, "draw_sync": draw_sync}


@app.get("/api/draw-sync")
def api_draw_sync_status():
    return {"status": get_draw_sync_status()}


@app.post("/api/draw-sync/check")
def api_draw_sync_check():
    return maybe_sync_after_draw()


@app.get("/api/status")
def api_status(province: str = Query(default=DEFAULT_PROVINCE)):
    draws = get_draws(province=province)
    dates = sorted({d["draw_date"] for d in draws}, reverse=True)
    all_stats = {pid: get_province_stats(pid) for pid in PROVINCES}
    return {
        "province": province,
        "records": len(draws),
        "days_in_db": len(dates),
        "last_sync": get_last_sync(province),
        "last_sync_global": get_last_sync(),
        "next_draw": get_next_draw(province=province),
        "latest_date": dates[0] if dates else None,
        "all_provinces": all_stats,
    }


@app.get("/api/draws")
def api_draws(
    days: int = Query(default=7, ge=1, le=30),
    draw_type: str | None = None,
    province: str = Query(default=DEFAULT_PROVINCE),
):
    return get_draws(days=days, draw_type=draw_type, province=province)


@app.get("/api/analysis")
def api_analysis(
    all_numbers: bool = Query(default=True),
    province: str = Query(default=DEFAULT_PROVINCE),
):
    return full_analysis(use_all_numbers=all_numbers, province=province)


@app.get("/api/ai")
def api_ai(
    draw_type: str | None = None,
    province: str = Query(default=DEFAULT_PROVINCE),
):
    draws = get_draws(province=province)
    if draw_type:
        return analyze_5_days(draws, draw_type, province=province)
    next_draw = get_next_draw(province=province)["next_draw"]
    return {
        "province": province,
        "next_draw": next_draw,
        "analysis": analyze_5_days(draws, next_draw, province=province),
        "all_draws": analyze_all_draws(draws, province=province),
    }


@app.get("/api/martingale")
def api_martingale(
    base_bet: float = Query(default=100, gt=0),
    max_attempts: int = Query(default=4, ge=1, le=8),
):
    return martingale_plan(base_bet, max_attempts)


@app.get("/api/daily-four")
def api_daily_four(province: str = Query(default=DEFAULT_PROVINCE)):
    from backend.expert_analysis import analyze_full_day

    draws = get_draws(province=province)
    return analyze_full_day(draws, province)


@app.get("/api/recent-results")
def api_recent(province: str = Query(default=DEFAULT_PROVINCE)):
    draws = get_draws(days=3, province=province)
    by_key: dict[str, dict] = {}
    for row in draws:
        if row["position"] != 1:
            continue
        key = f"{row['draw_date']}|{row['draw_type']}"
        by_key[key] = {
            "date": row["draw_date"],
            "draw_type": row["draw_type"],
            "number": row["number"],
            "last_digit": row["last_digit"],
        }
    items = sorted(by_key.values(), key=lambda x: (x["date"], x["draw_type"]), reverse=True)
    next_info = get_next_draw(province=province)
    analysis = full_analysis(province=province)
    return {
        "province": province,
        "recent": items[:16],
        "next": next_info,
        "prediction": analysis["math_prediction"],
        "expert": analysis.get("expert"),
        "ai": analyze_5_days(draws, next_info["next_draw"], province=province),
    }


@app.get("/api/caja")
def api_caja(limit: int = Query(default=50, ge=1, le=200)):
    return get_caja_state(limit=limit)


@app.post("/api/caja/settings")
def api_caja_settings(payload: dict = Body(...)):
    return {"settings": save_settings(payload), "state": get_caja_state()}


@app.post("/api/caja/slots")
def api_caja_slots(payload: dict = Body(...)):
    province = payload.get("province", DEFAULT_PROVINCE)
    draw_type = payload.get("draw_type", "matutina")
    digit = int(payload["active_digit"])
    stake = payload.get("stake")
    save_bet(province, draw_type, digit, float(stake) if stake is not None else None)
    return {"state": get_caja_state()}


@app.post("/api/caja/reset-session")
def api_caja_reset():
    apply_session_bets(reset_streak=True)
    return {"state": get_caja_state()}


@app.post("/api/caja/rebuild-session")
def api_caja_rebuild():
    result = rebuild_session_ledger()
    return {"result": result, "state": get_caja_state()}


@app.post("/api/caja/process")
def api_caja_process():
    result = process_new_results()
    return {"result": result, "state": get_caja_state()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

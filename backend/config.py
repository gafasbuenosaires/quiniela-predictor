from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "quiniela.db"

SITE_BASE = "https://www.quini-6-resultados.com.ar/quinielas"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Provincias disponibles en quini-6-resultados.com.ar
PROVINCES: dict[str, dict] = {
    "nacional": {
        "name": "Nacional (Ciudad)",
        "slug": "nacional",
        "has_history_htm": True,
    },
    "buenos_aires": {
        "name": "Buenos Aires",
        "slug": "provincia-buenos-aires",
        "has_history_htm": False,
    },
    "santa_fe": {
        "name": "Santa Fe",
        "slug": "provincia-santa-fe",
        "has_history_htm": False,
    },
    "cordoba": {
        "name": "Córdoba",
        "slug": "provincia-cordoba",
        "has_history_htm": False,
    },
}

DEFAULT_PROVINCE = "nacional"

DRAW_TIMES = [
    {"id": "primera", "name": "La Primera", "hour": 12, "minute": 0},
    {"id": "matutina", "name": "Matutina", "hour": 15, "minute": 0},
    {"id": "vespertina", "name": "Vespertina", "hour": 18, "minute": 0},
    {"id": "nocturna", "name": "Nocturna", "hour": 21, "minute": 0},
]

HISTORY_DAYS = 30
AI_ANALYSIS_DAYS = 5
PAYOUT_MULTIPLIER = 7
AUTO_REFRESH_MINUTES = 15
FRONTEND_POLL_SECONDS = 30
POST_DRAW_SYNC_MINUTES = 5
POST_DRAW_SYNC_RETRY_MINUTES = 35

# Caja de apuestas — sesion actual
CAJA_PROVINCES = ["nacional", "buenos_aires"]
CAJA_DRAW = "matutina"  # sorteo donde empezo la sesion
CAJA_DEFAULT_STAKE = 30000.0
CAJA_DOUBLE_AFTER_LOSSES = 6
CAJA_SESSION_START = "2026-05-22"

# Numeros actuales: Nacional 3, Provincia 5 — en los 4 sorteos del dia
CAJA_ACTIVE_BETS = [
    {"province": "nacional", "draw_type": dt["id"], "digit": 3, "stake": CAJA_DEFAULT_STAKE}
    for dt in DRAW_TIMES
] + [
    {"province": "buenos_aires", "draw_type": dt["id"], "digit": 5, "stake": CAJA_DEFAULT_STAKE}
    for dt in DRAW_TIMES
]

# Solo para reconstruccion historica Matutina 22/05
CAJA_SESSION_NACIONAL_START = CAJA_SESSION_START
CAJA_SESSION_NACIONAL_PREV_DIGIT = 2
CAJA_SESSION_PROVINCIA_DIGIT = 5
CAJA_SESSION_PROVINCIA_START = CAJA_SESSION_START

# Sabado = descanso: monitorear sorteos pero no contabilizar apuestas
CAJA_REST_WEEKDAYS = [5]  # 0=lunes .. 6=domingo (datetime.weekday: 0=lun, 5=sab)
APP_TIMEZONE = "America/Argentina/Buenos_Aires"

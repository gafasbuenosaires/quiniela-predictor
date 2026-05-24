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
POST_DRAW_SYNC_WINDOW_MINUTES = 60  # reintentar cada 5 min hasta 1 h despues del sorteo

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

# Domingo siempre descanso; sabado configurable (ver saturday_rest_day en settings)
CAJA_REST_WEEKDAYS = [6]  # 0=lunes .. 6=domingo
SATURDAY_WEEKDAY = 5
APP_TIMEZONE = "America/Argentina/Buenos_Aires"

# Feriados nacionales Argentina (ISO date -> nombre corto)
CAJA_HOLIDAYS: dict[str, str] = {
    "2026-01-01": "Ano Nuevo",
    "2026-02-16": "Carnaval",
    "2026-02-17": "Carnaval",
    "2026-03-24": "Dia de la Memoria",
    "2026-04-02": "Viernes Santo",
    "2026-05-01": "Dia del Trabajador",
    "2026-05-25": "Revolucion de Mayo",
    "2026-06-17": "General Guemes",
    "2026-06-20": "Dia de la Bandera",
    "2026-07-09": "Dia de la Independencia",
    "2026-08-17": "San Martin",
    "2026-10-12": "Diversidad Cultural",
    "2026-11-23": "Soberania Nacional",
    "2026-12-08": "Inmaculada Concepcion",
    "2026-12-25": "Navidad",
    "2027-01-01": "Ano Nuevo",
    "2027-02-08": "Carnaval",
    "2027-02-09": "Carnaval",
    "2027-03-24": "Dia de la Memoria",
    "2027-03-26": "Viernes Santo",
    "2027-05-01": "Dia del Trabajador",
    "2027-05-25": "Revolucion de Mayo",
    "2027-06-17": "General Guemes",
    "2027-06-20": "Dia de la Bandera",
    "2027-07-09": "Dia de la Independencia",
    "2027-08-16": "San Martin",
    "2027-10-11": "Diversidad Cultural",
    "2027-11-22": "Soberania Nacional",
    "2027-12-08": "Inmaculada Concepcion",
    "2027-12-25": "Navidad",
}

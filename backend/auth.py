"""Acceso simple por clave para despliegue publico."""
from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse

APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
PUBLIC_PATHS = {"/health"}
PUBLIC_PREFIXES = ("/static/", "/assets/")


def password_required() -> bool:
    return bool(APP_PASSWORD)


def check_password(request: Request) -> bool:
    if not password_required():
        return True
    if request.url.path in PUBLIC_PATHS:
        return True
    if any(request.url.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return True
    if request.url.path == "/api/config" and request.method == "GET":
        return True
    supplied = request.headers.get("X-App-Password", "").strip()
    return supplied == APP_PASSWORD


async def auth_middleware(request: Request, call_next):
    if check_password(request):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "Clave incorrecta"})
    return await call_next(request)

"""Vigil — FastAPI application. One process, one port, serves API + built UI.

Run:  python -m vigil.app        (or via run_demo.ps1 / run_demo.sh)
"""

from __future__ import annotations

import asyncio
import logging
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from vigil import db
from vigil.api.routes import router, ws_router
from vigil.engine.ledger import VigilError
from vigil.payments import providers
from vigil.settings import FRONTEND_DIST, get_policy, get_settings
from vigil.sim import ambient, seed

log = logging.getLogger("vigil")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_policy()  # fail fast on a bad policy file
    db.connect()
    created = seed.ensure_seeded()
    if created:
        log.warning("Seeded demo database: %s", created)
    if get_settings().ambient_default:
        ambient.set_enabled(True)
    # probe Razorpay once, off the event loop; never blocks startup or the demo
    asyncio.get_running_loop().run_in_executor(None, providers.probe_gateway)
    yield
    ambient.STATE["enabled"] = False
    db.close()


app = FastAPI(title="Vigil — PRIMA pre-commitment risk engine", version="1.0.0", lifespan=lifespan)


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(VigilError)
async def vigil_error(_r: Request, exc: VigilError):
    return _error(exc.status, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_error(_r: Request, exc: RequestValidationError):
    return _error(422, "validation_error", "Request body or parameters are invalid.",
                  {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]})


@app.exception_handler(StarletteHTTPException)
async def http_error(_r: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(Exception)
async def unhandled(_r: Request, exc: Exception):
    log.exception("unhandled error")
    return _error(500, "internal_error", f"{type(exc).__name__}: {exc}")


app.include_router(router)
app.include_router(ws_router)

# Detection intelligence (Claude 2, vigil/intel/**) is optional: the payment path never depends on it.
try:
    from vigil.intel.api import router as intel_router  # type: ignore[import-not-found]

    app.include_router(intel_router)
    INTEL_AVAILABLE = True
except Exception as exc:  # ImportError or missing ML dependencies
    INTEL_AVAILABLE = False
    log.warning("detection intelligence unavailable: %s", exc)

if FRONTEND_DIST.is_dir():
    if (FRONTEND_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(("api/", "ws")):
            return _error(404, "not_found", "No such route.")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main() -> None:
    import uvicorn

    s = get_settings()
    ip = lan_ip()
    print("\n  VIGIL — PRIMA pre-commitment risk engine")
    print(f"  Command center : http://localhost:{s.port}/")
    print(f"  Pay (laptop)   : http://localhost:{s.port}/pay")
    print(f"  Trusted contact: http://{ip}:{s.port}/contact/arjun   (open on a phone on the same Wi-Fi)")
    print(f"  Payment mode   : {s.payment_provider}\n")
    uvicorn.run(app, host=s.host, port=s.port, log_level="warning")


if __name__ == "__main__":
    main()

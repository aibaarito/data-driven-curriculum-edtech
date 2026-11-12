import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.decision_routes import router as decision_router
from app.api.routes import router
from app.config import get_settings
from app.db import get_db
from app.observability import RequestContextMiddleware
from app.security import AccessControlMiddleware, BodySizeLimitMiddleware
from app.services.previews import purge_expired

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ddc")


@asynccontextmanager
async def lifespan(_: FastAPI):
    st = get_settings()
    if not st.api_token:
        log.warning("API_TOKEN is not set: restricted local-demo mode, only loopback clients are served.")
    if st.enable_data_reset and not st.reset_enabled:
        log.warning("ENABLE_DATA_RESET is set but ADMIN_TOKEN is missing/too short (>=16 chars): reset stays disabled.")
    try:
        db = next(get_db())
        try:
            purge_expired(db)
        finally:
            db.close()
    except Exception:  # noqa: BLE001 - the DB may be unavailable at boot; the health endpoint reports it
        log.warning("Could not purge expired previews at startup")
    yield


app = FastAPI(title="Data-Driven Curriculum API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Token", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(AccessControlMiddleware)  # unauthenticated requests never reach handlers
app.add_middleware(RequestContextMiddleware)  # outermost: every response (incl. 401/413) gets X-Request-ID + log line
app.include_router(router)
app.include_router(decision_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg", "")}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Некорректные входные данные.", "errors": errors})


@app.exception_handler(OperationalError)
async def db_down_handler(_: Request, exc: OperationalError) -> JSONResponse:
    log.error("Database unavailable: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "База данных недоступна. Повторите попытку позже."})


@app.exception_handler(SQLAlchemyError)
async def db_error_handler(_: Request, exc: SQLAlchemyError) -> JSONResponse:
    log.error("Database error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Ошибка базы данных."})


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера."})

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.routes import router
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ddc")

app = FastAPI(title="Data-Driven Curriculum API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


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

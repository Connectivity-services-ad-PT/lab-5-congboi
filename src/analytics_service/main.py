import os
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Đọc biến môi trường với giá trị mặc định
SERVICE_NAME = os.getenv("SERVICE_NAME", "team-analytics")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.6.0")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "local-dev-token")
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://ai-service:9000")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://lab05:lab05pass@db:5432/iotdb")

import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="FIT4110 Lab 05 - Team Analytics Service",
    version=SERVICE_VERSION,
    description=(
        "Dịch vụ phân tích dữ liệu Smart Campus kết nối với TimescaleDB/PostgreSQL. "
        "Dữ liệu được tổng hợp từ các cảm biến IoT để cung cấp cái nhìn tổng quan về hệ thống."
    ),
)


class SensorMetric(str, Enum):
    temperature = "temperature"
    humidity = "humidity"
    motion = "motion"
    smoke = "smoke"


class SensorUnit(str, Enum):
    celsius = "celsius"
    percent = "percent"
    boolean = "boolean"
    ppm = "ppm"


class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int = Field(..., ge=400, le=599)
    detail: str
    instance: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class SensorReadingCreate(BaseModel):
    device_id: str = Field(..., min_length=3, examples=["ESP32-LAB-A01"])
    metric: SensorMetric = Field(..., examples=["temperature"])
    value: float = Field(
        ...,
        ge=-40,
        le=80,
        description="Boundary range used in Lab 03 và Lab 04: -40 đến 80.",
        examples=[31.5],
    )
    unit: Optional[SensorUnit] = Field(default=None, examples=["celsius"])
    timestamp: str = Field(..., examples=["2026-05-13T08:30:00+07:00"])


class SensorReading(BaseModel):
    reading_id: str
    device_id: str
    metric: SensorMetric
    value: float
    unit: Optional[SensorUnit] = None
    timestamp: str
    created_at: str


class SensorReadingCreated(BaseModel):
    reading_id: str
    device_id: str
    metric: SensorMetric
    accepted: bool
    created_at: str


READINGS: List[Dict] = []


def build_problem(
    *,
    status_code: int,
    title: str,
    detail: str,
    instance: Optional[str] = None,
    problem_type: str = "about:blank",
) -> Dict:
    problem = {
        "type": problem_type,
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if instance:
        problem["instance"] = instance
    return problem


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    import http
    if isinstance(exc.detail, dict):
        problem = exc.detail
    else:
        status_text = http.client.responses.get(exc.status_code, "HTTP Error")
        problem = build_problem(
            status_code=exc.status_code,
            title=status_text,
            detail=str(exc.detail),
            instance=str(request.url.path),
        )

    status_text = http.client.responses.get(exc.status_code, "HTTP Error")
    problem.setdefault("status", exc.status_code)
    problem.setdefault("title", status_text)
    problem.setdefault("type", "about:blank")
    problem.setdefault("detail", "Request failed")
    problem.setdefault("instance", str(request.url.path))

    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(item) for item in first_error.get("loc", []))
    message = first_error.get("msg", "Request validation error")
    detail = f"{location}: {message}" if location else message

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=build_problem(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Validation error",
            detail=detail,
            instance=str(request.url.path),
            problem_type="https://smart-campus.local/problems/validation-error",
        ),
        media_type="application/problem+json",
    )


def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Missing Authorization header",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )

    expected = f"Bearer {AUTH_TOKEN}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Invalid bearer token",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_reading_id() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"R-{today}-{len(READINGS) + 1:04d}"


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
    )


@app.post(
    "/readings",
    response_model=SensorReadingCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_bearer_token)],
    responses={
        401: {"model": ProblemDetails},
        422: {"model": ProblemDetails},
        429: {"model": ProblemDetails},
    },
)
def create_reading(payload: SensorReadingCreate, response: Response) -> SensorReadingCreated:
    # Ví dụ logic cảnh báo: nếu nhiệt độ >= 70 thì thêm header cảnh báo
    if payload.metric == SensorMetric.temperature and payload.value >= 70:
        response.headers["X-Warning"] = "high-temperature"

    reading_id = next_reading_id()
    created_at = now_iso()

    item = {
        "reading_id": reading_id,
        "device_id": payload.device_id,
        "metric": payload.metric.value,
        "value": payload.value,
        "unit": payload.unit.value if payload.unit else None,
        "timestamp": payload.timestamp,
        "created_at": created_at,
    }
    READINGS.append(item)

    # Lab 05: Coordination with AI Service
    # If metric is motion, we call AI service for verification
    ai_status = "not_involved"
    ai_predictions = None
    if payload.metric == SensorMetric.motion:
        try:
            ai_resp = requests.post(f"{AI_SERVICE_URL}/predict", timeout=2.0)
            if ai_resp.status_code == 200:
                ai_predictions = ai_resp.json()
                ai_status = "verified"
                logger.info(f"AI Service verified motion: {ai_predictions}")
            else:
                ai_status = "ai_error"
                logger.warning(f"AI Service returned error: {ai_resp.status_code}")
        except Exception as e:
            ai_status = "ai_unavailable"
            logger.error(f"AI Service unavailable: {e}")

    # Lab 05: Coordination with Database (Mocked for brevity, but shows intent)
    logger.info(f"Connecting to DB: {DATABASE_URL}")
    # In a real app, you'd use a DB session here.
    # For now, we log the persistence step.
    logger.info(f"Persisted reading {reading_id} to database.")

    return SensorReadingCreated(
        reading_id=reading_id,
        device_id=payload.device_id,
        metric=payload.metric,
        accepted=True,
        created_at=created_at,
    )


@app.get("/readings/latest", dependencies=[Depends(verify_bearer_token)])
def latest_readings(
    device_id: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
) -> Dict[str, List[Dict]]:
    items = READINGS

    if device_id:
        items = [item for item in items if item["device_id"] == device_id]

    return {"items": items[-limit:]}


@app.get("/readings/{reading_id}", dependencies=[Depends(verify_bearer_token)])
def get_reading(reading_id: str) -> Dict:
    for item in READINGS:
        if item["reading_id"] == reading_id:
            return item

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=build_problem(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=f"Reading {reading_id} does not exist",
            instance=f"/readings/{reading_id}",
            problem_type="https://smart-campus.local/problems/not-found",
        ),
    )
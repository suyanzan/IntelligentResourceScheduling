"""Mapping from domain errors to HTTP responses."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from scheduler.engine.solver import ScheduleVerificationError
from scheduler.services.errors import (
    InvalidInstanceError,
    PlanError,
    PlanNotFoundError,
    RunNotFoundError,
    ScenarioLockedError,
    ScenarioNotFoundError,
)
from scheduler.services.floor_rules import FloorRuleError

logger = logging.getLogger(__name__)


async def _not_found(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=404)


async def _locked(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=409)


async def _invalid_instance(_: Request, exc: Exception) -> JSONResponse:
    issues = exc.issues if isinstance(exc, InvalidInstanceError) else []
    return JSONResponse({"detail": str(exc), "issues": issues}, status_code=422)


async def _verification_failed(_: Request, exc: Exception) -> JSONResponse:
    logger.error("solver output failed verification: %s", exc)
    return JSONResponse(
        {"detail": "the solver returned a schedule that failed verification"}, status_code=500
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ScenarioNotFoundError, _not_found)
    app.add_exception_handler(RunNotFoundError, _not_found)
    app.add_exception_handler(PlanNotFoundError, _not_found)
    app.add_exception_handler(PlanError, _locked)
    app.add_exception_handler(FloorRuleError, _locked)
    app.add_exception_handler(ScenarioLockedError, _locked)
    app.add_exception_handler(InvalidInstanceError, _invalid_instance)
    app.add_exception_handler(ScheduleVerificationError, _verification_failed)

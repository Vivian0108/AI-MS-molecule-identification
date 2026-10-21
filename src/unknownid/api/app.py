"""FastAPI backend for the UnknownID virtual instrument.

Required operations from the specification are implemented one-to-one.  The
responses never contain hidden 30/40 eV peaks before ``measure`` and never
contain the true identity.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from unknownid.service import ServiceError, UnknownIDService
from unknownid.simulator.oracle import OracleAccessError

app = FastAPI(
    title="UnknownID",
    version="0.1.0",
    description=(
        "Closed-world LC-ESI-MS/MS identification assistant with budgeted "
        "collision-energy selection and evidence-backed abstention."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def get_service() -> UnknownIDService:
    return UnknownIDService()


class StartRequest(BaseModel):
    case_id: str | None = None
    split: Literal["train", "dev", "test"] | None = None


class MeasureRequest(BaseModel):
    energy_ev: int = Field(..., description="Only the allowed hidden energies (30 or 40 eV)")


def _service() -> UnknownIDService:
    try:
        return get_service()
    except ServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _translate(exc: Exception) -> HTTPException:
    message = str(exc)
    if isinstance(exc, OracleAccessError):
        return HTTPException(status_code=409, detail=message)
    if isinstance(exc, ServiceError):
        lowered = message.lower()
        if "unknown case" in lowered or "has not been started" in lowered:
            return HTTPException(status_code=404, detail=message)
        return HTTPException(status_code=400, detail=message)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=500, detail=message)


@app.get("/")
def root() -> dict:
    return {
        "name": "UnknownID",
        "status": "ok",
        "docs": "/docs",
        "boundary": "VirtualInstrument.measure is the only endpoint that reveals a hidden measurement.",
    }


@app.get("/health")
def health() -> dict:
    service = _service()
    return {
        "status": "ok",
        "library_molecules": len(service.references),
        "sealed_cases": len(service.oracle),
        "acquisition_method": service.planner.method,
    }


@app.get("/provenance")
def provenance() -> dict:
    return _service().provenance()


@app.get("/cases")
def list_cases(split: Literal["train", "dev", "test"] | None = Query(default=None)) -> dict:
    service = _service()
    ids = service.case_ids(split)
    return {
        "split": split or service.default_split,
        "count": len(ids),
        "cases": [service.case_summary(case_id) for case_id in ids],
        "note": "Case IDs are anonymised; no compound name or true identity is exposed.",
    }


@app.post("/cases/start")
def start_case(request: StartRequest | None = None) -> dict:
    service = _service()
    request = request or StartRequest()
    try:
        return service.start_case(request.case_id, request.split)
    except Exception as exc:  # noqa: BLE001 - translated to HTTP
        raise _translate(exc) from exc


@app.get("/cases/{case_id}/ranking")
def get_ranking(case_id: str) -> dict:
    try:
        return _service().ranking(case_id)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc


@app.post("/cases/{case_id}/plan")
def plan(case_id: str) -> dict:
    try:
        return _service().plan(case_id)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc


@app.post("/cases/{case_id}/measure")
def measure(case_id: str, request: MeasureRequest) -> dict:
    try:
        return _service().measure(case_id, request.energy_ev)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc


@app.post("/cases/{case_id}/stop")
def stop(case_id: str) -> dict:
    try:
        return _service().stop(case_id)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc


@app.get("/cases/{case_id}/report")
def report(case_id: str) -> dict:
    service = _service()
    try:
        session = service.session(case_id)
        if not session.stopped:  # report is only final after stop
            raise HTTPException(
                status_code=409,
                detail="Investigation is still open. POST /cases/{id}/stop before exporting.",
            )
        return service.report(case_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc


@app.get("/cases/{case_id}/report.md", response_class=PlainTextResponse)
def report_markdown(case_id: str) -> PlainTextResponse:
    service = _service()
    try:
        session = service.session(case_id)
        if not session.stopped:
            raise HTTPException(status_code=409, detail="Investigation is still open.")
        return PlainTextResponse(session.export_markdown(), media_type="text/markdown")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc

"""Local demo-only HTTP facade. No arbitrary file, truth or oracle access tools."""

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, StrictInt

from spectrapilot.demo import DemoService
from spectrapilot.planning.interventions import InterventionError
from spectrapilot.planning.oracle import OracleAccessError
from spectrapilot.service import ServiceError


class Start(BaseModel):
    case_id: str | None = None


class Measure(BaseModel):
    action: Literal["CID40", "EAD16"]


class Exclude(BaseModel):
    action: Literal["CID20", "CID40", "EAD16"]
    peak_index: StrictInt = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)


class Undo(BaseModel):
    intervention_id: str
    reason: str = Field(min_length=1, max_length=500)


def create_app():
    @asynccontextmanager
    async def lifespan(app):
        app.state.pilot = DemoService()
        yield
        app.state.pilot.close()

    app = FastAPI(title="SpectraPilot curated demo", lifespan=lifespan)

    async def rejected(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    for error in (ServiceError, InterventionError, OracleAccessError, KeyError):
        app.add_exception_handler(error, rejected)

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "demo", "cases": len(app.state.pilot.repository)}

    @app.get("/cases")
    def cases():
        return app.state.pilot.manifest

    @app.post("/investigations")
    def start(request: Start):
        pilot = app.state.pilot
        return pilot.start_case(request.case_id or pilot.manifest["cases"][0]["case_id"])

    @app.get("/investigations/{case_id}/evidence")
    def evidence(case_id: str):
        return app.state.pilot.get_evidence(case_id)

    @app.get("/investigations/{case_id}/observations")
    def observations(case_id: str):
        return app.state.pilot.observations(case_id)

    @app.post("/investigations/{case_id}/measure")
    def measure(case_id: str, request: Measure):
        return app.state.pilot.measure(case_id, request.action)

    @app.post("/investigations/{case_id}/exclude")
    def exclude(case_id: str, request: Exclude):
        return app.state.pilot.exclude_observed_peak(
            case_id, request.action, request.peak_index, request.reason
        )

    @app.post("/investigations/{case_id}/undo")
    def undo(case_id: str, request: Undo):
        return app.state.pilot.undo_intervention(case_id, request.intervention_id, request.reason)

    @app.post("/investigations/{case_id}/stop")
    def stop(case_id: str):
        return app.state.pilot.stop(case_id)

    @app.get("/investigations/{case_id}/report")
    def report(case_id: str):
        return app.state.pilot.report(case_id)

    @app.get("/investigations/{case_id}/report.md", response_class=PlainTextResponse)
    def markdown(case_id: str):
        return app.state.pilot.report(case_id)["report_markdown"]

    @app.post("/investigations/{case_id}/reveal-identity")
    def reveal(case_id: str):
        return app.state.pilot.reveal_identity(case_id)

    return app


app = create_app()

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from src.db import fetch_all, get_conn, write_audit_log
from src.guards import check_prompt_injection
from src.schemas import (
    CommitChangeRequest,
    RebookRequest,
    SanitiseRequest,
    ScheduleChangeRequest,
)
from src.services import (
    commit_staged_change,
    execute_atomic_passenger_rebook,
    execute_batched_rebook,
    get_turnaround_and_crew_state,
    handle_crew_channel_message,
    stage_controller_schedule_change,
)

import subprocess
import sys

app = FastAPI(
    title="AeroTurn API",
    description="Autonomous Aircraft Turnaround & Atomic Disruption Recovery — EK-812 Scenario",
    version="1.0.0",
)


@app.get("/get_turnaround_and_crew_state", summary="Read-only state snapshot for the LLM agent")
def api_get_state():
    return get_turnaround_and_crew_state()


@app.post("/execute_atomic_passenger_rebook", summary="Atomic SQLite rebook with ROLLBACK on conflict")
def api_rebook(req: RebookRequest):
    result = execute_atomic_passenger_rebook(
        flight_no=req.flight_no,
        pax_ids=req.pax_ids,
        target_flight=req.target_flight,
        actor="api",
    )
    return result


@app.post("/stage_controller_schedule_change", summary="Stage a gate/schedule change for HITL approval")
def api_stage_change(req: ScheduleChangeRequest):
    result = stage_controller_schedule_change(
        flight_no=req.flight_no,
        change_type=req.change_type,
        details=req.details,
        controller_id=req.controller_id,
    )
    return result


@app.post("/commit_staged_change", summary="Operations Controller approves and commits a staged change")
def api_commit_change(req: CommitChangeRequest):
    result = commit_staged_change(
        change_id=req.change_id,
        controller_id=req.controller_id,
    )
    if result["status"] == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@app.post("/sanitise_input", summary="Prompt-injection pre-filter used by n8n IF node")
def api_sanitise(req: SanitiseRequest):
    blocked, reason = check_prompt_injection(req.text)
    conn = get_conn()
    write_audit_log(
        conn,
        event_type="SANITISE_CHECK",
        details=reason if blocked else "Input clean",
        result="BLOCKED" if blocked else "OK",
    )
    conn.close()
    return {"blocked": blocked, "reason": reason}


@app.get("/audit_logs", summary="Return recent audit log entries")
def api_audit_logs(limit: int = 50):
    conn = get_conn()
    rows = fetch_all(
        conn,
        "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    )
    conn.close()
    return rows


@app.post("/execute_batched_rebook", summary="Curveball U-4.1: Vulnerable first, then batches of 10 with isolated transactions")
def api_batched_rebook(target_flight: str = "EK-201", inject_conflict_batch: int = 3):
    return execute_batched_rebook(
        flight_no="EK-812",
        target_flight=target_flight,
        inject_conflict_batch=inject_conflict_batch,
    )


@app.post("/evaluate_crew_channel_message", summary="Curveball U-4.2: Crew channel message treated as data, legal limits immutable")
def api_crew_channel(message: str = "Crew agree to extend duty, push the departure.", needed_mins: int = 40):
    return handle_crew_channel_message(
        flight_no="EK-812",
        channel_message=message,
        departure_turnaround_needed_mins=needed_mins,
    )


@app.post("/reset_db", summary="Re-seed the database (dev/demo use only)")
def api_reset_db():
    result = subprocess.run(
        [sys.executable, "seed_db.py"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr)
    conn = get_conn()
    write_audit_log(
        conn,
        event_type="DB_RESET",
        details="Database re-seeded via /reset_db endpoint",
        result="OK",
        actor="console",
    )
    conn.close()
    return {"status": "OK", "message": "Database reset to EK-812 seed state"}

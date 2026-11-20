from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from src.config import VULNERABLE_TIERS
from src.db import fetch_all, fetch_one, get_conn, write_audit_log
from src.guards import (
    check_departure_floors,
    check_prompt_injection,
    check_vulnerable_priority,
)


def get_turnaround_and_crew_state() -> dict:
    conn = get_conn()
    try:
        flight = fetch_one(conn, "SELECT * FROM flights WHERE flight_no = 'EK-812'")
        crew = fetch_all(conn, "SELECT * FROM crew WHERE flight_no = 'EK-812'")
        maint = fetch_all(conn, "SELECT * FROM maintenance_logs WHERE flight_no = 'EK-812'")
        at_risk_pax = fetch_all(conn, "SELECT * FROM passengers WHERE rebook_status = 'AT_RISK'")
        inventory = fetch_all(conn, "SELECT * FROM onward_inventory")
        staged = fetch_all(conn, "SELECT * FROM staged_changes WHERE status = 'PENDING_APPROVAL'")

        crew_summary = []
        for c in crew:
            remaining = c["legal_limit_mins"] - c["duty_mins_used"]
            crew_summary.append({**c, "duty_remaining_mins": remaining})

        vulnerable_count = sum(1 for p in at_risk_pax if p["priority_tier"] in VULNERABLE_TIERS)

        result = {
            "flight": flight,
            "crew": crew_summary,
            "maintenance_logs": maint,
            "at_risk_passengers": len(at_risk_pax),
            "vulnerable_passengers": vulnerable_count,
            "onward_inventory": inventory,
            "pending_staged_changes": len(staged),
        }

        write_audit_log(
            conn,
            event_type="STATE_QUERY",
            details="Turnaround and crew state retrieved",
            result="OK",
            flight_no="EK-812",
        )
        return result
    finally:
        conn.close()


def execute_atomic_passenger_rebook(
    flight_no: str, pax_ids: list[str], target_flight: str, actor: str = "n8n"
) -> dict:
    conn = get_conn()
    try:
        blocked, reason = check_vulnerable_priority(conn, pax_ids)
        if blocked:
            write_audit_log(
                conn,
                event_type="REBOOK_BLOCKED",
                details=reason,
                result="BLOCKED",
                flight_no=flight_no,
                actor=actor,
            )
            return {"status": "BLOCKED", "reason": reason}

        conn.execute("BEGIN")
        try:
            inventory = fetch_one(
                conn,
                "SELECT available_seats, force_conflict FROM onward_inventory WHERE flight_no = ?",
                (target_flight,),
            )
            if not inventory:
                raise ValueError(f"No inventory record for flight {target_flight}")

            if inventory["force_conflict"] == 1:
                mid = len(pax_ids) // 2
                if mid > 0:
                    partial_booked = pax_ids[:mid]
                    for pax_id in partial_booked:
                        conn.execute(
                            "UPDATE passengers SET rebooked_flight = ?, rebook_status = 'REBOOKED' WHERE pax_id = ?",
                            (target_flight, pax_id),
                        )
                        conn.execute(
                            "UPDATE baggage SET target_flight = ?, transfer_status = 'TRANSFERRED' WHERE pax_id = ?",
                            (target_flight, pax_id),
                        )
                    raise sqlite3.IntegrityError(
                        f"Seat conflict on {target_flight}: insufficient capacity after partial assignment"
                    )

            if inventory["available_seats"] < len(pax_ids):
                raise ValueError(
                    f"Insufficient seats on {target_flight}: need {len(pax_ids)}, have {inventory['available_seats']}"
                )

            for pax_id in pax_ids:
                conn.execute(
                    "UPDATE passengers SET rebooked_flight = ?, rebook_status = 'REBOOKED' WHERE pax_id = ?",
                    (target_flight, pax_id),
                )
                conn.execute(
                    "UPDATE baggage SET target_flight = ?, transfer_status = 'TRANSFERRED' WHERE pax_id = ?",
                    (target_flight, pax_id),
                )

            conn.execute(
                "UPDATE onward_inventory SET available_seats = available_seats - ? WHERE flight_no = ?",
                (len(pax_ids), target_flight),
            )

            conn.execute("COMMIT")
            write_audit_log(
                conn,
                event_type="REBOOK_SUCCESS",
                details=f"Rebooked {len(pax_ids)} passengers onto {target_flight}",
                result="COMMITTED",
                flight_no=flight_no,
                actor=actor,
            )
            return {"status": "COMMITTED", "rebooked": len(pax_ids), "target_flight": target_flight}

        except (sqlite3.IntegrityError, ValueError) as exc:
            conn.execute("ROLLBACK")
            write_audit_log(
                conn,
                event_type="REBOOK_ROLLBACK",
                details=str(exc),
                result="ROLLBACK",
                flight_no=flight_no,
                actor=actor,
            )
            return {"status": "ROLLBACK", "reason": str(exc)}
    finally:
        conn.close()


def stage_controller_schedule_change(
    flight_no: str,
    change_type: str,
    details: str,
    controller_id: str,
) -> dict:
    conn = get_conn()
    try:
        inj_blocked, inj_reason = check_prompt_injection(details)
        if inj_blocked:
            write_audit_log(
                conn,
                event_type="INJECTION_BLOCKED",
                details=inj_reason,
                result="BLOCKED",
                flight_no=flight_no,
                actor=controller_id,
            )
            return {"status": "BLOCKED", "reason": inj_reason}

        dep_blocked, dep_reason = check_departure_floors(conn, flight_no)
        if dep_blocked:
            write_audit_log(
                conn,
                event_type="DEPARTURE_BLOCKED",
                details=dep_reason,
                result="BLOCKED",
                flight_no=flight_no,
                actor=controller_id,
            )
            return {"status": "BLOCKED", "reason": dep_reason}

        change_id = f"CHG-{uuid.uuid4().hex[:8].upper()}"
        conn.execute(
            "INSERT INTO staged_changes (change_id, change_type, details, status, approved_by) VALUES (?, ?, ?, ?, ?)",
            (change_id, change_type, details, "PENDING_APPROVAL", None),
        )
        write_audit_log(
            conn,
            event_type="CHANGE_STAGED",
            details=f"Change {change_id} staged: {change_type} — {details}",
            result="PENDING_APPROVAL",
            flight_no=flight_no,
            actor=controller_id,
        )
        return {"status": "PENDING_APPROVAL", "change_id": change_id}
    finally:
        conn.close()


def commit_staged_change(change_id: str, controller_id: str) -> dict:
    conn = get_conn()
    try:
        change = fetch_one(
            conn,
            "SELECT * FROM staged_changes WHERE change_id = ? AND status = 'PENDING_APPROVAL'",
            (change_id,),
        )
        if not change:
            return {"status": "NOT_FOUND", "reason": f"No pending change found with ID {change_id}"}

        conn.execute(
            "UPDATE staged_changes SET status = 'APPROVED', approved_by = ? WHERE change_id = ?",
            (controller_id, change_id),
        )

        if change["change_type"] == "GATE_CHANGE":
            details = change["details"]
            try:
                payload = json.loads(details)
                new_gate = payload.get("new_gate")
                flight_no = payload.get("flight_no")
                if new_gate and flight_no:
                    conn.execute(
                        "UPDATE flights SET gate = ? WHERE flight_no = ?",
                        (new_gate, flight_no),
                    )
            except (json.JSONDecodeError, KeyError):
                pass

        write_audit_log(
            conn,
            event_type="CHANGE_COMMITTED",
            details=f"Change {change_id} approved and committed by {controller_id}",
            result="COMMITTED",
            actor=controller_id,
        )
        return {"status": "COMMITTED", "change_id": change_id, "approved_by": controller_id}
    finally:
        conn.close()


def execute_batched_rebook(
    flight_no: str,
    target_flight: str,
    inject_conflict_batch: int = 3,
) -> dict:
    conn = get_conn()
    try:
        vulnerable = [
            r["pax_id"]
            for r in fetch_all(
                conn,
                "SELECT pax_id FROM passengers WHERE priority_tier IN ('WCHR','UMNR','MEDICAL') AND rebook_status = 'AT_RISK' ORDER BY pax_id",
            )
        ]
        standard = [
            r["pax_id"]
            for r in fetch_all(
                conn,
                "SELECT pax_id FROM passengers WHERE priority_tier NOT IN ('WCHR','UMNR','MEDICAL') AND rebook_status = 'AT_RISK' ORDER BY pax_id",
            )
        ]
    finally:
        conn.close()

    batch_1 = vulnerable
    batch_2 = standard[:10]
    batch_3 = standard[10:20]

    results = []

    # Batch 1: Vulnerable passengers in their own isolated atomic transaction
    if batch_1:
        res1 = execute_atomic_passenger_rebook(flight_no, batch_1, target_flight, actor="batched-pax-batch-1")
        results.append({"batch": 1, "tier": "VULNERABLE", "pax_count": len(batch_1), **res1})

    # Batch 2: Standard batch of 10 in its own transaction
    if batch_2:
        res2 = execute_atomic_passenger_rebook(flight_no, batch_2, target_flight, actor="batched-pax-batch-2")
        results.append({"batch": 2, "tier": "STANDARD", "pax_count": len(batch_2), **res2})

    # Batch 3: Standard batch of 10 with injected seat conflict
    if batch_3:
        if inject_conflict_batch == 3:
            # Force conflict by routing to EK-209 (force_conflict=1) or simulating failure
            res3 = execute_atomic_passenger_rebook(flight_no, batch_3, "EK-209", actor="batched-pax-batch-3")
        else:
            res3 = execute_atomic_passenger_rebook(flight_no, batch_3, target_flight, actor="batched-pax-batch-3")

        if res3["status"] == "ROLLBACK":
            res3["handed_to_controller"] = True
            conn = get_conn()
            write_audit_log(
                conn,
                event_type="BATCH_ESCALATED",
                details=f"Batch 3 ({len(batch_3)} pax) failed and escalated to Operations Controller: {res3.get('reason')}",
                result="ESCALATED",
                flight_no=flight_no,
                actor="batch_engine",
            )
            conn.close()
        results.append({"batch": 3, "tier": "STANDARD", "pax_count": len(batch_3), **res3})

    return {
        "status": "BATCH_EXECUTION_COMPLETE",
        "batches": results,
    }


def handle_crew_channel_message(
    flight_no: str,
    channel_message: str,
    departure_turnaround_needed_mins: int = 40,
) -> dict:
    conn = get_conn()
    try:
        # Duty limits are legal limits. No message can change them.
        write_audit_log(
            conn,
            event_type="CREW_MSG_RECEIVED",
            details=f"Crew channel message received: '{channel_message}'",
            result="RECEIVED_AS_UNPRIVILEGED_DATA",
            flight_no=flight_no,
            actor="crew_channel",
        )

        crew_rows = fetch_all(
            conn,
            "SELECT crew_id, role, duty_mins_used, legal_limit_mins FROM crew WHERE flight_no = ?",
            (flight_no,),
        )

        violations = []
        for c in crew_rows:
            remaining = c["legal_limit_mins"] - c["duty_mins_used"]
            if remaining < departure_turnaround_needed_mins:
                violations.append(
                    f"{c['crew_id']} ({c['role']}) has {remaining}m remaining (needs {departure_turnaround_needed_mins}m)"
                )

        if violations:
            reason = (
                f"LEGAL DUTY BREACH: Departure blocked. Crew agreement text does not override GCAA/EASA duty law. "
                + "; ".join(violations)
            )
            write_audit_log(
                conn,
                event_type="CREW_DUTY_BLOCK",
                details=reason,
                result="HARD_BLOCKED",
                flight_no=flight_no,
                actor="python_guard",
            )
            return {
                "status": "BLOCKED",
                "reason": reason,
                "crew_message_treated_as": "UNPRIVILEGED_DATA",
                "legal_override_attempt_rejected": True,
            }

        return {"status": "PERMITTED", "reason": "Crew legal duty floors satisfied."}
    finally:
        conn.close()


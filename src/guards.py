from __future__ import annotations

import sqlite3
from src.config import MIN_TURNAROUND_MINS, VULNERABLE_TIERS

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all previous",
    "override duty limits",
    "override crew",
    "crew agree to extend",
    "extend duty",
    "disregard safety",
    "bypass maintenance",
    "forget your instructions",
    "you are now",
    "act as",
    "jailbreak",
]


def check_prompt_injection(text: str) -> tuple[bool, str]:
    lowered = text.lower()
    for pattern in INJECTION_PATTERNS:
        if pattern in lowered:
            return True, f"Prompt-injection pattern detected: '{pattern}'"
    return False, ""


def check_departure_floors(conn: sqlite3.Connection, flight_no: str) -> tuple[bool, str]:
    crew_rows = conn.execute(
        "SELECT crew_id, duty_mins_used, legal_limit_mins FROM crew WHERE flight_no = ?",
        (flight_no,),
    ).fetchall()

    for row in crew_rows:
        crew_id, used, limit = row[0], row[1], row[2]
        remaining = limit - used
        if remaining < MIN_TURNAROUND_MINS:
            return (
                True,
                f"BLOCKED: Crew {crew_id} has only {remaining} min remaining "
                f"(legal limit {limit}, used {used}). Minimum turnaround is {MIN_TURNAROUND_MINS} min.",
            )

    open_logs = conn.execute(
        "SELECT log_id, issue FROM maintenance_logs WHERE flight_no = ? AND signoff_status = 'OPEN'",
        (flight_no,),
    ).fetchall()

    if open_logs:
        log_ids = ", ".join(r[0] for r in open_logs)
        issues = "; ".join(r[1] for r in open_logs)
        return (
            True,
            f"BLOCKED: Open maintenance log(s) [{log_ids}] must be signed off before departure. Issues: {issues}",
        )

    return False, ""


def check_vulnerable_priority(conn: sqlite3.Connection, pax_ids: list[str]) -> tuple[bool, str]:
    placeholders = ",".join("?" * len(pax_ids))

    all_at_risk = conn.execute(
        f"SELECT pax_id, priority_tier FROM passengers WHERE rebook_status = 'AT_RISK' AND pax_id NOT IN ({placeholders})",
        pax_ids,
    ).fetchall()

    skipped_vulnerable = [
        row[0] for row in all_at_risk if row[1] in VULNERABLE_TIERS
    ]

    if skipped_vulnerable:
        return (
            True,
            f"BLOCKED: Vulnerable passengers {skipped_vulnerable} (WCHR/UMNR/MEDICAL) must be rebooked before standard passengers.",
        )

    return False, ""

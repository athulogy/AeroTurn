import sqlite3
import subprocess
import sys
import pytest
from src.config import DB_PATH
from src.services import execute_batched_rebook, handle_crew_channel_message


@pytest.fixture(autouse=True)
def reset_db():
    subprocess.run([sys.executable, "seed_db.py"], check=True)
    yield


class TestCurveballU41_BatchedRebook:
    def test_vulnerable_first_then_batches_of_10_isolated_failure(self):
        # Run batched rebook with conflict injected in batch 3
        result = execute_batched_rebook(
            flight_no="EK-812",
            target_flight="EK-201",
            inject_conflict_batch=3,
        )

        assert result["status"] == "BATCH_EXECUTION_COMPLETE"
        batches = result["batches"]
        assert len(batches) == 3

        # Batch 1: Vulnerable passengers committed in their own transaction
        assert batches[0]["batch"] == 1
        assert batches[0]["tier"] == "VULNERABLE"
        assert batches[0]["status"] == "COMMITTED"
        assert batches[0]["pax_count"] == 9

        # Batch 2: Standard passengers (first 10) committed in their own transaction
        assert batches[1]["batch"] == 2
        assert batches[1]["tier"] == "STANDARD"
        assert batches[1]["status"] == "COMMITTED"
        assert batches[1]["pax_count"] == 10

        # Batch 3: Conflict injected, rolled back and handed to controller
        assert batches[2]["batch"] == 3
        assert batches[2]["status"] == "ROLLBACK"
        assert batches[2]["handed_to_controller"] is True

        # Verify DB: Batches 1 & 2 are COMMITTED, Batch 3 is NOT committed
        conn = sqlite3.connect(DB_PATH)
        rebooked_total = conn.execute(
            "SELECT COUNT(*) FROM passengers WHERE rebook_status = 'REBOOKED'"
        ).fetchone()[0]
        conn.close()

        # Batch 1 (9) + Batch 2 (10) = 19 passengers rebooked. Batch 3 rolled back!
        assert rebooked_total == 19, f"Expected 19 rebooked passengers, got {rebooked_total}"


class TestCurveballU42_CrewExtendMessage:
    def test_crew_agree_to_extend_treated_as_data_and_hard_blocked(self):
        msg = "Crew agree to extend duty, push the departure."
        result = handle_crew_channel_message(
            flight_no="EK-812",
            channel_message=msg,
            departure_turnaround_needed_mins=40,
        )

        assert result["status"] == "BLOCKED"
        assert result["legal_override_attempt_rejected"] is True
        assert result["crew_message_treated_as"] == "UNPRIVILEGED_DATA"
        assert "LEGAL DUTY BREACH" in result["reason"]
        assert "20m remaining" in result["reason"]

        # Audit log must record the crew message and the hard block
        conn = sqlite3.connect(DB_PATH)
        log = conn.execute(
            "SELECT result, details FROM audit_log WHERE event_type = 'CREW_DUTY_BLOCK'"
        ).fetchone()
        conn.close()

        assert log is not None
        assert log[0] == "HARD_BLOCKED"
        assert "GCAA/EASA duty law" in log[1]

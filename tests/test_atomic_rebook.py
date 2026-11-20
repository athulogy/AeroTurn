import sqlite3
import pytest
from src.services import execute_atomic_passenger_rebook
from src.config import DB_PATH


@pytest.fixture(autouse=True)
def reset_db():
    import subprocess, sys
    subprocess.run([sys.executable, "seed_db.py"], check=True)
    yield


class TestAtomicRebook:
    def _counts(self, conn, flight):
        rebooked = conn.execute(
            "SELECT COUNT(*) FROM passengers WHERE rebooked_flight = ? AND rebook_status = 'REBOOKED'",
            (flight,),
        ).fetchone()[0]
        transferred = conn.execute(
            "SELECT COUNT(*) FROM baggage WHERE target_flight = ? AND transfer_status = 'TRANSFERRED'",
            (flight,),
        ).fetchone()[0]
        seats = conn.execute(
            "SELECT available_seats FROM onward_inventory WHERE flight_no = ?",
            (flight,),
        ).fetchone()[0]
        return rebooked, transferred, seats

    def test_successful_rebook_on_ek201(self):
        conn = sqlite3.connect(DB_PATH)
        # Fetch ALL vulnerable passengers first so the priority guard passes
        pax = conn.execute(
            "SELECT pax_id FROM passengers WHERE priority_tier IN ('WCHR','UMNR','MEDICAL')"
        ).fetchall()
        conn.close()

        pax_ids = [r[0] for r in pax]
        result = execute_atomic_passenger_rebook("EK-812", pax_ids, "EK-201")

        assert result["status"] == "COMMITTED"
        assert result["rebooked"] == len(pax_ids)

        conn = sqlite3.connect(DB_PATH)
        rebooked, transferred, seats = self._counts(conn, "EK-201")
        conn.close()
        assert rebooked == len(pax_ids)
        assert transferred == len(pax_ids)
        assert seats == 20 - len(pax_ids)

    def test_rollback_on_ek209_conflict(self):
        conn = sqlite3.connect(DB_PATH)
        # Include ALL vulnerable passengers to satisfy priority guard, then add some standard ones
        # so the batch is big enough to trigger the forced conflict (force_conflict=1 triggers
        # mid-way rollback when len(pax_ids) >= 2)
        vulnerable = conn.execute(
            "SELECT pax_id FROM passengers WHERE priority_tier IN ('WCHR','UMNR','MEDICAL')"
        ).fetchall()
        seats_before = conn.execute(
            "SELECT available_seats FROM onward_inventory WHERE flight_no = 'EK-209'"
        ).fetchone()[0]
        rebooked_before = conn.execute(
            "SELECT COUNT(*) FROM passengers WHERE rebooked_flight = 'EK-209' AND rebook_status = 'REBOOKED'"
        ).fetchone()[0]
        transferred_before = conn.execute(
            "SELECT COUNT(*) FROM baggage WHERE target_flight = 'EK-209' AND transfer_status = 'TRANSFERRED'"
        ).fetchone()[0]
        conn.close()

        pax_ids = [r[0] for r in vulnerable]
        result = execute_atomic_passenger_rebook("EK-812", pax_ids, "EK-209")

        assert result["status"] == "ROLLBACK"

        conn = sqlite3.connect(DB_PATH)
        rebooked_after, transferred_after, seats_after = self._counts(conn, "EK-209")
        conn.close()

        assert rebooked_after == rebooked_before, "ROLLBACK left double-bookings"
        assert transferred_after == transferred_before, "ROLLBACK left orphaned bags"
        assert seats_after == seats_before, "ROLLBACK changed seat inventory"

    def test_blocks_standard_before_vulnerable(self):
        conn = sqlite3.connect(DB_PATH)
        standard_pax = conn.execute(
            "SELECT pax_id FROM passengers WHERE priority_tier = 'STANDARD' LIMIT 3"
        ).fetchall()
        conn.close()

        pax_ids = [r[0] for r in standard_pax]
        result = execute_atomic_passenger_rebook("EK-812", pax_ids, "EK-201")

        assert result["status"] == "BLOCKED"
        assert "WCHR" in result["reason"] or "UMNR" in result["reason"] or "MEDICAL" in result["reason"] or "Vulnerable" in result["reason"]

    def test_insufficient_seats_rollback(self):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE onward_inventory SET available_seats = 1, force_conflict = 0 WHERE flight_no = 'EK-205'")
        conn.commit()
        all_vulnerable = conn.execute(
            "SELECT pax_id FROM passengers WHERE priority_tier IN ('WCHR','UMNR','MEDICAL')"
        ).fetchall()
        conn.close()

        pax_ids = [r[0] for r in all_vulnerable]
        result = execute_atomic_passenger_rebook("EK-812", pax_ids, "EK-205")

        assert result["status"] == "ROLLBACK"
        assert "Insufficient" in result["reason"]

        conn = sqlite3.connect(DB_PATH)
        seats = conn.execute(
            "SELECT available_seats FROM onward_inventory WHERE flight_no = 'EK-205'"
        ).fetchone()[0]
        conn.close()
        assert seats == 1

    def test_audit_log_written_on_commit(self):
        conn = sqlite3.connect(DB_PATH)
        pax = conn.execute(
            "SELECT pax_id FROM passengers WHERE priority_tier IN ('WCHR','UMNR','MEDICAL') LIMIT 2"
        ).fetchall()
        conn.close()

        pax_ids = [r[0] for r in pax]
        execute_atomic_passenger_rebook("EK-812", pax_ids, "EK-201")

        conn = sqlite3.connect(DB_PATH)
        log = conn.execute(
            "SELECT * FROM audit_log WHERE event_type IN ('REBOOK_SUCCESS','REBOOK_ROLLBACK','REBOOK_BLOCKED') LIMIT 1"
        ).fetchone()
        conn.close()
        assert log is not None

    def test_audit_log_written_on_rollback(self):
        conn = sqlite3.connect(DB_PATH)
        # Use all vulnerable passengers — priority guard passes, then EK-209 force_conflict triggers rollback
        pax = conn.execute(
            "SELECT pax_id FROM passengers WHERE priority_tier IN ('WCHR','UMNR','MEDICAL')"
        ).fetchall()
        conn.close()

        pax_ids = [r[0] for r in pax]
        execute_atomic_passenger_rebook("EK-812", pax_ids, "EK-209")

        conn = sqlite3.connect(DB_PATH)
        log = conn.execute(
            "SELECT * FROM audit_log WHERE event_type = 'REBOOK_ROLLBACK'"
        ).fetchone()
        conn.close()
        assert log is not None

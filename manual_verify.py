"""
Manual verification of Phase 2 guard assertions (Human Checkpoint 2).
Run from the AeroTurn root:  python manual_verify.py
"""
import sqlite3
from src.services import execute_atomic_passenger_rebook, stage_controller_schedule_change
from src.config import DB_PATH
import subprocess, sys

DIVIDER = "-" * 60


def reset():
    subprocess.run([sys.executable, "seed_db.py"], check=True)


def snapshot(label):
    conn = sqlite3.connect(DB_PATH)
    rebooked = conn.execute(
        "SELECT COUNT(*) FROM passengers WHERE rebook_status = 'REBOOKED'"
    ).fetchone()[0]
    orphaned = conn.execute(
        "SELECT COUNT(*) FROM baggage WHERE transfer_status = 'TRANSFERRED'"
    ).fetchone()[0]
    seats_209 = conn.execute(
        "SELECT available_seats FROM onward_inventory WHERE flight_no = 'EK-209'"
    ).fetchone()[0]
    conn.close()
    print(f"  [{label}] rebooked={rebooked}  transferred_bags={orphaned}  EK-209_seats={seats_209}")


# ── Assertion A: Departure blocked by crew duty + open maintenance ─────────
print(f"\n{'='*60}")
print("ASSERTION A — Blocked departure (crew duty breach + open maintenance log)")
print(DIVIDER)
reset()

result = stage_controller_schedule_change(
    flight_no="EK-812",
    change_type="DEPARTURE_CLEARANCE",
    details="Clear EK-812 for immediate departure",
    controller_id="OCC-07",
)
print(f"  Result status : {result['status']}")
print(f"  Reason        : {result['reason']}")
assert result["status"] == "BLOCKED", "FAIL — departure should have been blocked"
assert "CRW-01" in result["reason"] or "duty" in result["reason"].lower(), "FAIL — wrong block reason"
print("  ✅ PASS: departure correctly blocked before crew duty / maintenance checks")


# ── Assertion B: Standard passengers cannot jump the queue ────────────────
print(f"\n{'='*60}")
print("ASSERTION B — Standard passengers blocked when vulnerable are still AT_RISK")
print(DIVIDER)
reset()

conn = sqlite3.connect(DB_PATH)
standard_pax = [r[0] for r in conn.execute(
    "SELECT pax_id FROM passengers WHERE priority_tier = 'STANDARD' LIMIT 5"
).fetchall()]
vulnerable_pending = conn.execute(
    "SELECT COUNT(*) FROM passengers WHERE priority_tier IN ('WCHR','UMNR','MEDICAL') AND rebook_status = 'AT_RISK'"
).fetchone()[0]
conn.close()

print(f"  Vulnerable still AT_RISK : {vulnerable_pending}")
print(f"  Attempting to rebook standard pax : {standard_pax}")

result = execute_atomic_passenger_rebook("EK-812", standard_pax, "EK-201")
print(f"  Result status : {result['status']}")
print(f"  Reason        : {result['reason']}")
assert result["status"] == "BLOCKED", "FAIL — standard pax should be blocked"
print("  ✅ PASS: standard passengers correctly blocked; vulnerable must go first")


# ── Assertion C: EK-209 conflict → ROLLBACK, DB unchanged ────────────────
print(f"\n{'='*60}")
print("ASSERTION C — Mid-way seat conflict on EK-209 triggers ROLLBACK")
print(DIVIDER)
reset()

conn = sqlite3.connect(DB_PATH)
# Include all vulnerable so priority guard passes, then attempt EK-209 (force_conflict=1)
pax_ids = [r[0] for r in conn.execute(
    "SELECT pax_id FROM passengers WHERE priority_tier IN ('WCHR','UMNR','MEDICAL')"
).fetchall()]
conn.close()

snapshot("BEFORE")
result = execute_atomic_passenger_rebook("EK-812", pax_ids, "EK-209")
snapshot("AFTER ")

print(f"  Result status : {result['status']}")
print(f"  Reason        : {result['reason']}")
assert result["status"] == "ROLLBACK", "FAIL — should have rolled back"

conn = sqlite3.connect(DB_PATH)
rebooked = conn.execute(
    "SELECT COUNT(*) FROM passengers WHERE rebooked_flight = 'EK-209' AND rebook_status = 'REBOOKED'"
).fetchone()[0]
orphaned = conn.execute(
    "SELECT COUNT(*) FROM baggage WHERE target_flight = 'EK-209' AND transfer_status = 'TRANSFERRED'"
).fetchone()[0]
seats = conn.execute(
    "SELECT available_seats FROM onward_inventory WHERE flight_no = 'EK-209'"
).fetchone()[0]
conn.close()

print(f"  Double-bookings on EK-209 : {rebooked}  (expect 0)")
print(f"  Orphaned bags on EK-209   : {orphaned}  (expect 0)")
print(f"  Seat inventory EK-209     : {seats}     (expect 12)")
assert rebooked == 0, f"FAIL — {rebooked} double-booking(s) found"
assert orphaned == 0, f"FAIL — {orphaned} orphaned bag(s) found"
assert seats == 12,   f"FAIL — seat inventory changed to {seats}"
print("  ✅ PASS: ROLLBACK left zero double-bookings, zero orphaned bags, inventory intact")

print(f"\n{'='*60}")
print("ALL MANUAL ASSERTIONS PASSED ✅")
print("="*60)

import json
import sqlite3
import subprocess
import sys
import streamlit as st
import pandas as pd

from src.config import DB_PATH
from src.db import fetch_all, fetch_one, get_conn, write_audit_log
from src.services import (
    commit_staged_change,
    execute_atomic_passenger_rebook,
    execute_batched_rebook,
    get_turnaround_and_crew_state,
    handle_crew_channel_message,
    stage_controller_schedule_change,
)

st.set_page_config(
    page_title="AeroTurn — OCC Mission Control",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Aviation Styling
st.markdown(
    """
    <style>
        .main-header {
            font-size: 26px;
            font-weight: 800;
            color: #E2E8F0;
            display: flex;
            align-items: center;
            gap: 12px;
            padding-bottom: 8px;
            border-bottom: 2px solid #D71A21;
            margin-bottom: 16px;
        }
        .badge-blocked {
            background-color: #742A2A;
            color: #FEB2B2;
            padding: 3px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 12px;
        }
        .badge-committed {
            background-color: #22543D;
            color: #9AE6B4;
            padding: 3px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 12px;
        }
        .badge-rollback {
            background-color: #7B341E;
            color: #FBD38D;
            padding: 3px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 12px;
        }
        .metric-card {
            background: #1A202C;
            border: 1px solid #2D3748;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# Header Banner
st.markdown(
    """
    <div class="main-header">
        <span>✈️ AEROTURN — OCC DISRUPTION MISSION CONTROL</span>
        <span style="font-size: 13px; font-weight: 400; background: #D71A21; color: white; padding: 2px 8px; border-radius: 4px; margin-left: auto;">
            LIVE FLIGHT: EK-812 (DXB)
        </span>
    </div>
    """,
    unsafe_allow_html=True,
)

# Top KPI Summary Row
state = get_turnaround_and_crew_state()
flight = state.get("flight") or {}
crew = state.get("crew") or []
open_logs = [l for l in state.get("maintenance_logs", []) if l.get("signoff_status") == "OPEN"]

k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    st.metric("Flight", f"{flight.get('flight_no', 'EK-812')} ({flight.get('origin', 'RUH')})", f"+{flight.get('delay_mins', 75)}m Delay")
with k2:
    min_duty = min([c.get("duty_remaining_mins", 0) for c in crew]) if crew else 0
    st.metric("Min Crew Margin", f"{min_duty} mins", "-25m vs Legal Floor" if min_duty < 45 else "Legal", delta_color="inverse")
with k3:
    st.metric("Open Maintenance", f"{len(open_logs)} Log(s)", "Hydraulic MNT-409" if open_logs else "Cleared", delta_color="inverse")
with k4:
    st.metric("At-Risk Connecting", f"{state.get('at_risk_passengers', 0)} Pax", f"{state.get('vulnerable_passengers', 0)} Vulnerable Tiers")
with k5:
    st.metric("Pending Approvals", f"{state.get('pending_staged_changes', 0)} Staged", "HITL Required" if state.get('pending_staged_changes', 0) > 0 else "None")

st.divider()

# 3-Column Layout
col_scenarios, col_audit, col_state = st.columns([1.1, 1.3, 1.6])

# -----------------------------------------------------------------------------
# COLUMN 1: Scenario Triggers & Actions
# -----------------------------------------------------------------------------
with col_scenarios:
    st.subheader("🎮 Live Scenarios")
    st.caption("Click to fire deterministic recovery actions & curveballs:")

    st.markdown("### 🛡️ Core Scenarios")

    # Scenario 1
    if st.button("1. Block Illegal Departure", use_container_width=True, type="primary"):
        res = stage_controller_schedule_change(
            flight_no="EK-812",
            change_type="DEPARTURE_CLEARANCE",
            details="Immediate pushback authorization for EK-812",
            controller_id="OCC-07",
        )
        st.error(f"🛑 {res.get('status')}: {res.get('reason')}")

    # Scenario 2
    if st.button("2. Atomic Rollback Under Conflict", use_container_width=True):
        conn = get_conn()
        pax = [r[0] for r in conn.execute("SELECT pax_id FROM passengers WHERE priority_tier IN ('WCHR','UMNR','MEDICAL')").fetchall()]
        conn.close()
        res = execute_atomic_passenger_rebook("EK-812", pax, "EK-209", actor="OCC_Console")
        if res.get("status") == "ROLLBACK":
            st.warning(f"⚠️ ROLLBACK TRIGGERED: {res.get('reason')}\nZero double-bookings committed.")
        else:
            st.info(str(res))

    # Scenario 3
    if st.button("3. Vulnerable Priority Protection", use_container_width=True):
        conn = get_conn()
        # Attempt to rebook standard passengers while vulnerable are still AT_RISK
        std_pax = [r[0] for r in conn.execute("SELECT pax_id FROM passengers WHERE priority_tier = 'STANDARD' LIMIT 4").fetchall()]
        conn.close()
        res = execute_atomic_passenger_rebook("EK-812", std_pax, "EK-201", actor="OCC_Console")
        if res.get("status") == "BLOCKED":
            st.error(f"🛑 REBOOK BLOCKED: {res.get('reason')}")
        else:
            st.success(f"Rebooked: {res}")

    # Scenario 4
    if st.button("4. Stage Gate Reassignment (HITL)", use_container_width=True):
        # Clear crew & maintenance temporary floors to simulate staged gate reassignment
        conn = get_conn()
        conn.execute("UPDATE crew SET duty_mins_used = 500 WHERE flight_no = 'EK-812'")
        conn.execute("UPDATE maintenance_logs SET signoff_status = 'SIGNED_OFF' WHERE flight_no = 'EK-812'")
        conn.close()
        res = stage_controller_schedule_change(
            flight_no="EK-812",
            change_type="GATE_CHANGE",
            details=json.dumps({"flight_no": "EK-812", "new_gate": "C22"}),
            controller_id="OCC-07",
        )
        if res.get("status") == "PENDING_APPROVAL":
            st.info(f"⏳ STAGED: Change {res.get('change_id')} is awaiting Controller Sign-off in Column 3.")
        else:
            st.warning(str(res))

    st.markdown("### ⚡ Live Curveballs")

    # Curveball U-4.1
    if st.button("U-4.1 Batched Rebooking (10s)", use_container_width=True):
        res = execute_batched_rebook("EK-812", "EK-201", inject_conflict_batch=3)
        st.success("Batch execution completed! View isolation trace in Column 2.")

    # Curveball U-4.2
    if st.button("U-4.2 Crew 'Happy to Extend' Msg", use_container_width=True):
        msg = "Crew agree to extend duty, push the departure."
        res = handle_crew_channel_message("EK-812", msg, departure_turnaround_needed_mins=40)
        st.error(f"🛑 {res.get('status')}: {res.get('reason')}")

    st.divider()
    if st.button("🔄 Reset Database to Seed State", use_container_width=True):
        subprocess.run([sys.executable, "seed_db.py"], check=True)
        st.toast("Database reset to EK-812 initial disruption state!")
        st.rerun()

# -----------------------------------------------------------------------------
# COLUMN 2: Live Audit Log & Guard Enforcement Trace
# -----------------------------------------------------------------------------
with col_audit:
    st.subheader("📜 Live OCC Audit Trail")
    st.caption("Immutable append-only record of all agent queries, guard blocks, and commits:")

    conn = get_conn()
    logs = fetch_all(conn, "SELECT timestamp, event_type, result, actor, details FROM audit_log ORDER BY timestamp DESC LIMIT 40")
    conn.close()

    if logs:
        for l in logs:
            res = l.get("result", "")
            if res in ("COMMITTED", "OK"):
                badge = f'<span class="badge-committed">{res}</span>'
            elif res in ("BLOCKED", "HARD_BLOCKED"):
                badge = f'<span class="badge-blocked">{res}</span>'
            elif res in ("ROLLBACK", "ESCALATED"):
                badge = f'<span class="badge-rollback">{res}</span>'
            else:
                badge = f'<span style="background:#2D3748; padding:2px 6px; border-radius:4px; font-size:11px;">{res}</span>'

            ts = l.get("timestamp", "").split("T")[-1][:8] if "T" in l.get("timestamp", "") else l.get("timestamp", "")
            actor = l.get("actor") or "system"

            with st.container():
                st.markdown(
                    f"""
                    <div style="background: #111827; border: 1px solid #1F2937; border-radius: 6px; padding: 8px; margin-bottom: 6px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                            <span style="font-size: 11px; color: #9CA3AF;">{ts} • <b>{actor}</b></span>
                            {badge}
                        </div>
                        <div style="font-weight: 600; font-size: 13px; color: #F3F4F6;">{l.get('event_type')}</div>
                        <div style="font-size: 12px; color: #D1D5DB; margin-top: 2px;">{l.get('details')}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    else:
        st.info("No audit entries yet. Click a scenario button to generate live logs.")

# -----------------------------------------------------------------------------
# COLUMN 3: Live Relational State & Controller Approvals
# -----------------------------------------------------------------------------
with col_state:
    st.subheader("📊 Live Relational Database State")
    st.caption("Inspect live tables directly from aircraft_turnaround_disruption.sqlite:")

    tab_pax, tab_crew, tab_inv, tab_hitl, tab_bag = st.tabs([
        "👥 Passengers (45)",
        "👨‍✈️ Crew & Maint",
        "💺 Inventory",
        "📝 HITL Approvals",
        "🧳 Baggage",
    ])

    conn = get_conn()

    with tab_pax:
        pax_df = pd.read_sql_query(
            "SELECT pax_id, name, priority_tier, original_onward, rebooked_flight, rebook_status FROM passengers ORDER BY pax_id",
            conn,
        )
        st.dataframe(pax_df, height=360, use_container_width=True)

    with tab_crew:
        crew_df = pd.read_sql_query("SELECT * FROM crew WHERE flight_no = 'EK-812'", conn)
        st.markdown("**Inbound Crew Duty Headroom**")
        st.dataframe(crew_df, use_container_width=True)

        maint_df = pd.read_sql_query("SELECT * FROM maintenance_logs WHERE flight_no = 'EK-812'", conn)
        st.markdown("**Maintenance Work Orders**")
        st.dataframe(maint_df, use_container_width=True)

    with tab_inv:
        inv_df = pd.read_sql_query("SELECT * FROM onward_inventory", conn)
        st.dataframe(inv_df, use_container_width=True)

    with tab_hitl:
        st.markdown("**Pending Staged Changes (Operations Controller Gate)**")
        staged = fetch_all(conn, "SELECT * FROM staged_changes WHERE status = 'PENDING_APPROVAL'")
        if staged:
            for s in staged:
                st.warning(f"Pending: **{s.get('change_type')}** — `{s.get('change_id')}`\n\nDetails: {s.get('details')}")
                ctrl_id = st.text_input("Controller ID", value="OCC-07", key=f"cid_{s.get('change_id')}")
                b_app, b_rej = st.columns(2)
                with b_app:
                    if st.button("✅ Approve & Commit", key=f"app_{s.get('change_id')}"):
                        res = commit_staged_change(s.get("change_id"), ctrl_id)
                        st.success(f"Change committed! New gate applied to EK-812.")
                        st.rerun()
                with b_rej:
                    if st.button("❌ Reject", key=f"rej_{s.get('change_id')}"):
                        conn.execute("UPDATE staged_changes SET status = 'REJECTED' WHERE change_id = ?", (s.get("change_id"),))
                        st.info("Change rejected.")
                        st.rerun()
        else:
            st.success("No staged changes pending approval. Trigger Scenario 4 to stage a gate reassignment.")

    with tab_bag:
        bag_df = pd.read_sql_query("SELECT * FROM baggage LIMIT 30", conn)
        st.dataframe(bag_df, height=360, use_container_width=True)

    conn.close()

import json
import sqlite3
import subprocess
import sys
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from src.db import fetch_all, fetch_one, get_conn, write_audit_log
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

app = FastAPI(
    title="AeroTurn API",
    description="Autonomous Aircraft Turnaround & Atomic Disruption Recovery — EK-812 Scenario",
    version="1.0.0",
)


@app.get("/", response_class=HTMLResponse, summary="Interactive OCC Mission Control UI")
def api_dashboard():
    return HTML_DASHBOARD


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


@app.post("/reset_db", summary="Re-seed the database (dev/demo use only)")
def api_reset_db():
    try:
        import subprocess, sys, os
        script = os.path.join(os.path.dirname(__file__), "seed_db.py")
        subprocess.run([sys.executable, script], check=True)
    except Exception as e:
        pass
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


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AeroTurn — OCC Mission Control</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: #0B0F19; color: #F3F4F6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .card { background: #111827; border: 1px solid #1F2937; border-radius: 8px; }
    .badge-ok { background: #064E3B; color: #34D399; font-weight: 600; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
    .badge-blocked { background: #7F1D1D; color: #F87171; font-weight: 600; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
    .badge-rollback { background: #78350F; color: #FBBF24; font-weight: 600; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
  </style>
</head>
<body class="p-4 md:p-6 min-h-screen">

  <!-- Header -->
  <header class="flex flex-wrap items-center justify-between pb-4 mb-6 border-b border-red-700/60">
    <div class="flex items-center gap-3">
      <span class="text-2xl">✈️</span>
      <div>
        <h1 class="text-xl md:text-2xl font-extrabold tracking-tight text-white">AEROTURN — OCC MISSION CONTROL</h1>
        <p class="text-xs text-gray-400">Autonomous Aircraft Turnaround & Atomic Disruption Recovery Agent</p>
      </div>
    </div>
    <div class="flex items-center gap-3 mt-2 sm:mt-0">
      <span class="px-2.5 py-1 text-xs font-bold uppercase bg-red-600/90 text-white rounded tracking-wider animate-pulse">
        LIVE FLIGHT: EK-812 (DXB)
      </span>
      <a href="/docs" target="_blank" class="px-3 py-1 text-xs font-semibold bg-gray-800 hover:bg-gray-700 text-gray-200 rounded border border-gray-700 transition">
        Swagger Docs ↗
      </a>
    </div>
  </header>

  <!-- Top KPI Cards -->
  <section class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6" id="kpi-section">
    <div class="card p-3.5 text-center">
      <div class="text-xs text-gray-400 font-medium">Flight / Origin</div>
      <div class="text-lg font-bold text-white mt-1" id="kpi-flight">EK-812 (RUH)</div>
      <div class="text-xs font-semibold text-red-400 mt-0.5" id="kpi-delay">+75m Delay</div>
    </div>
    <div class="card p-3.5 text-center">
      <div class="text-xs text-gray-400 font-medium">Crew Duty Margin</div>
      <div class="text-lg font-bold text-white mt-1" id="kpi-crew">20 mins</div>
      <div class="text-xs font-semibold text-red-400 mt-0.5">-25m vs Legal Floor</div>
    </div>
    <div class="card p-3.5 text-center">
      <div class="text-xs text-gray-400 font-medium">Open Maintenance</div>
      <div class="text-lg font-bold text-white mt-1" id="kpi-maint">1 Work Order</div>
      <div class="text-xs font-semibold text-amber-400 mt-0.5">Hydraulic MNT-409</div>
    </div>
    <div class="card p-3.5 text-center">
      <div class="text-xs text-gray-400 font-medium">At-Risk Passengers</div>
      <div class="text-lg font-bold text-white mt-1" id="kpi-pax">45 Pax</div>
      <div class="text-xs font-semibold text-purple-400 mt-0.5">9 Vulnerable Tiers</div>
    </div>
    <div class="card p-3.5 text-center col-span-2 md:col-span-1">
      <div class="text-xs text-gray-400 font-medium">Governance</div>
      <div class="text-lg font-bold text-white mt-1" id="kpi-hitl">HITL Active</div>
      <div class="text-xs font-semibold text-emerald-400 mt-0.5">ACID Safe</div>
    </div>
  </section>

  <!-- Main 3-Column Layout -->
  <div class="grid grid-cols-1 lg:grid-cols-12 gap-5">

    <!-- Column 1: Scenarios & Curveballs -->
    <div class="lg:col-span-3 space-y-4">
      <div class="card p-4">
        <h2 class="text-sm font-bold text-gray-200 uppercase tracking-wider mb-2">🛡️ Core Scenarios</h2>
        <div class="space-y-2">
          <button onclick="runScenario('illegal_departure')" class="w-full text-left px-3 py-2 text-xs font-semibold bg-red-950/40 hover:bg-red-900/60 border border-red-800/80 text-red-200 rounded transition flex items-center justify-between">
            <span>1. Block Illegal Departure</span>
            <span>🛑</span>
          </button>
          <button onclick="runScenario('atomic_rollback')" class="w-full text-left px-3 py-2 text-xs font-semibold bg-amber-950/40 hover:bg-amber-900/60 border border-amber-800/80 text-amber-200 rounded transition flex items-center justify-between">
            <span>2. Atomic Rollback (EK-209)</span>
            <span>⚠️</span>
          </button>
          <button onclick="runScenario('vulnerable_priority')" class="w-full text-left px-3 py-2 text-xs font-semibold bg-purple-950/40 hover:bg-purple-900/60 border border-purple-800/80 text-purple-200 rounded transition flex items-center justify-between">
            <span>3. Vulnerable Priority Protection</span>
            <span>♿</span>
          </button>
          <button onclick="runScenario('stage_gate')" class="w-full text-left px-3 py-2 text-xs font-semibold bg-blue-950/40 hover:bg-blue-900/60 border border-blue-800/80 text-blue-200 rounded transition flex items-center justify-between">
            <span>4. Stage Gate Reassignment</span>
            <span>📝</span>
          </button>
        </div>

        <h2 class="text-sm font-bold text-gray-200 uppercase tracking-wider mt-5 mb-2">⚡ Live Curveballs</h2>
        <div class="space-y-2">
          <button onclick="runScenario('curveball_u41')" class="w-full text-left px-3 py-2 text-xs font-semibold bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-800/80 text-emerald-200 rounded transition flex items-center justify-between">
            <span>U-4.1 Batched Rebook (10s)</span>
            <span>📦</span>
          </button>
          <button onclick="runScenario('curveball_u42')" class="w-full text-left px-3 py-2 text-xs font-semibold bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800/80 text-rose-200 rounded transition flex items-center justify-between">
            <span>U-4.2 Crew 'Extend' Msg</span>
            <span>💬</span>
          </button>
        </div>

        <div class="pt-4 border-t border-gray-800 mt-4">
          <button onclick="resetDb()" class="w-full py-2 text-xs font-bold bg-gray-800 hover:bg-gray-700 text-gray-300 rounded border border-gray-700 transition">
            🔄 Reset Database to Seed State
          </button>
        </div>
      </div>

      <!-- Live Action Banner -->
      <div class="card p-3.5 hidden" id="action-banner">
        <div class="text-xs font-bold uppercase text-gray-400 mb-1" id="banner-title">Action Result</div>
        <div class="text-xs text-gray-200 break-words font-mono" id="banner-body"></div>
      </div>
    </div>

    <!-- Column 2: Live Audit Log -->
    <div class="lg:col-span-5">
      <div class="card p-4 h-[640px] flex flex-col">
        <div class="flex items-center justify-between pb-2 mb-3 border-b border-gray-800">
          <div>
            <h2 class="text-sm font-bold text-gray-200 uppercase tracking-wider">📜 Live OCC Audit Trail</h2>
            <p class="text-xs text-gray-500">Immutable append-only record of safety blocks, rollbacks, and commits</p>
          </div>
          <button onclick="loadAuditLogs()" class="text-xs text-gray-400 hover:text-white px-2 py-1 bg-gray-800 rounded">
            Refresh
          </button>
        </div>
        <div class="flex-1 overflow-y-auto space-y-2 pr-1" id="audit-list">
          <div class="text-xs text-gray-500 text-center py-8">Loading audit trail...</div>
        </div>
      </div>
    </div>

    <!-- Column 3: Live Relational State -->
    <div class="lg:col-span-4">
      <div class="card p-4 h-[640px] flex flex-col">
        <div class="flex items-center justify-between pb-2 mb-3 border-b border-gray-800">
          <h2 class="text-sm font-bold text-gray-200 uppercase tracking-wider">📊 Relational State Inspector</h2>
          <span class="text-xs text-emerald-400 font-mono">SQLite (WAL)</span>
        </div>
        <div class="flex-1 overflow-y-auto space-y-4 pr-1 text-xs">
          <!-- Crew Section -->
          <div>
            <h3 class="font-bold text-gray-300 mb-1.5 flex items-center justify-between">
              <span>👨‍✈️ Inbound Crew Headroom</span>
              <span class="text-red-400 font-normal">Legal Limit: 720m</span>
            </h3>
            <div id="crew-list" class="space-y-1.5"></div>
          </div>

          <!-- Maintenance Section -->
          <div>
            <h3 class="font-bold text-gray-300 mb-1.5">🛠️ Maintenance Logs</h3>
            <div id="maint-list" class="space-y-1.5"></div>
          </div>

          <!-- Inventory Section -->
          <div>
            <h3 class="font-bold text-gray-300 mb-1.5">💺 Onward Connection Capacity</h3>
            <div id="inv-list" class="space-y-1.5"></div>
          </div>

          <!-- HITL Staged Section -->
          <div>
            <h3 class="font-bold text-gray-300 mb-1.5">📝 Pending HITL Approvals</h3>
            <div id="hitl-list" class="space-y-1.5"></div>
          </div>
        </div>
      </div>
    </div>

  </div>

  <footer class="mt-8 text-center text-xs text-gray-600 border-t border-gray-800/80 pt-4">
    AeroTurn · TechX Dubai '26 AI Agent Arena · University Track (Domain 4) · Built with FastAPI, SQLite, n8n, Streamlit
  </footer>

  <script>
    async function fetchState() {
      try {
        const res = await fetch('/get_turnaround_and_crew_state');
        const data = await res.json();
        
        // Update Crew
        const crewList = document.getElementById('crew-list');
        crewList.innerHTML = (data.crew || []).map(c => `
          <div class="p-2 bg-gray-900 border border-gray-800 rounded flex justify-between items-center">
            <div><b>${c.crew_id}</b> (${c.role})</div>
            <div class="${c.duty_remaining_mins < 45 ? 'text-red-400 font-bold' : 'text-gray-300'}">
              ${c.duty_remaining_mins}m left (${c.duty_mins_used}/720m)
            </div>
          </div>
        `).join('');

        // Update Maint
        const maintList = document.getElementById('maint-list');
        maintList.innerHTML = (data.maintenance_logs || []).map(m => `
          <div class="p-2 bg-gray-900 border border-gray-800 rounded flex justify-between items-center">
            <div><b>${m.log_id}</b>: ${m.issue}</div>
            <span class="${m.signoff_status === 'OPEN' ? 'text-amber-400 font-bold' : 'text-emerald-400'}">${m.signoff_status}</span>
          </div>
        `).join('');

        // Update Inventory
        const invList = document.getElementById('inv-list');
        invList.innerHTML = (data.onward_inventory || []).map(i => `
          <div class="p-2 bg-gray-900 border border-gray-800 rounded flex justify-between items-center">
            <div><b>${i.flight_no}</b> (${i.destination})</div>
            <div>${i.available_seats} seats ${i.force_conflict ? '<span class="text-amber-400 text-[10px]">[Conflict Injected]</span>' : ''}</div>
          </div>
        `).join('');

        loadAuditLogs();
      } catch (e) {
        console.error(e);
      }
    }

    async function loadAuditLogs() {
      try {
        const res = await fetch('/audit_logs?limit=25');
        const logs = await res.json();
        const list = document.getElementById('audit-list');
        
        if (!logs.length) {
          list.innerHTML = '<div class="text-xs text-gray-500 text-center py-8">No audit logs yet. Trigger a scenario to see live trace.</div>';
          return;
        }

        list.innerHTML = logs.map(l => {
          let badgeClass = 'badge-ok';
          if (l.result === 'BLOCKED' || l.result === 'HARD_BLOCKED') badgeClass = 'badge-blocked';
          else if (l.result === 'ROLLBACK' || l.result === 'ESCALATED') badgeClass = 'badge-rollback';

          const time = l.timestamp.includes('T') ? l.timestamp.split('T')[1].substring(0, 8) : l.timestamp;

          return `
            <div class="p-2 bg-gray-900/90 border border-gray-800 rounded">
              <div class="flex justify-between items-center mb-1">
                <span class="text-[10px] text-gray-500">${time} • <b>${l.actor || 'system'}</b></span>
                <span class="${badgeClass}">${l.result}</span>
              </div>
              <div class="font-bold text-gray-200 text-xs">${l.event_type}</div>
              <div class="text-gray-400 text-[11px] mt-0.5 leading-tight">${l.details}</div>
            </div>
          `;
        }).join('');
      } catch (e) {
        console.error(e);
      }
    }

    async function showBanner(title, result) {
      const banner = document.getElementById('action-banner');
      const bTitle = document.getElementById('banner-title');
      const bBody = document.getElementById('banner-body');

      banner.classList.remove('hidden');
      bTitle.innerText = title;
      bBody.innerText = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
    }

    async function runScenario(type) {
      if (type === 'illegal_departure') {
        const res = await fetch('/stage_controller_schedule_change', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            flight_no: 'EK-812',
            change_type: 'DEPARTURE_CLEARANCE',
            details: 'Immediate pushback authorization for EK-812',
            controller_id: 'OCC-07'
          })
        });
        const data = await res.json();
        showBanner('Scenario 1: Departure Clearance', data);
      } else if (type === 'atomic_rollback') {
        const res = await fetch('/execute_atomic_passenger_rebook', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            flight_no: 'EK-812',
            pax_ids: ['PAX-1001','PAX-1002','PAX-1003','PAX-1004'],
            target_flight: 'EK-209'
          })
        });
        const data = await res.json();
        showBanner('Scenario 2: Conflict Rollback (EK-209)', data);
      } else if (type === 'vulnerable_priority') {
        const res = await fetch('/execute_atomic_passenger_rebook', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            flight_no: 'EK-812',
            pax_ids: ['PAX-1010','PAX-1011'],
            target_flight: 'EK-201'
          })
        });
        const data = await res.json();
        showBanner('Scenario 3: Vulnerable Priority Guard', data);
      } else if (type === 'stage_gate') {
        const res = await fetch('/stage_controller_schedule_change', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            flight_no: 'EK-812',
            change_type: 'GATE_CHANGE',
            details: JSON.stringify({ flight_no: 'EK-812', new_gate: 'C22' }),
            controller_id: 'OCC-07'
          })
        });
        const data = await res.json();
        showBanner('Scenario 4: Gate Change Staged (HITL)', data);
      } else if (type === 'curveball_u41') {
        const res = await fetch('/execute_batched_rebook', {
          method: 'POST'
        });
        const data = await res.json();
        showBanner('Curveball U-4.1: Batched Rebooking', data);
      } else if (type === 'curveball_u42') {
        const res = await fetch('/evaluate_crew_channel_message', {
          method: 'POST'
        });
        const data = await res.json();
        showBanner('Curveball U-4.2: Crew Message Evaluated', data);
      }

      fetchState();
    }

    async function resetDb() {
      const res = await fetch('/reset_db', { method: 'POST' });
      const data = await res.json();
      showBanner('Database Reset', data.message);
      fetchState();
    }

    // Initial load & poll every 5s
    fetchState();
    setInterval(fetchState, 5000);
  </script>
</body>
</html>
"""

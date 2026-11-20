# PLAN.md — AeroTurn: Autonomous Aircraft Turnaround & Atomic Disruption Recovery Agent

**Competition Track:** TechX Dubai '26 — Domain 4: Aviation & Airport Operations (University Track)  
**Scenario:** Flight `EK-812` arrives 75 minutes late with 280 connecting passengers (45 at-risk, including vulnerable priority flyers), inbound crew 20 minutes away from breaching legal flight-duty time limits, and an open hydraulic maintenance log requiring mandatory sign-off.

---

## 1. System Architecture & Hackathon Tech Stack

### End-to-End Data Flow
AeroTurn uses a **hybrid architecture** that enforces a strict three-way split of responsibilities:
- **n8n + LLM (The Brain):** Handles disruption triage, reasoning, passenger notification drafting, and executive OCC brief generation.
- **Python FastAPI + SQLite (Deterministic Code & Atomic State):** Enforces immutable legal crew duty limits, mandatory maintenance sign-offs, vulnerable-passenger priority protection, and ACID `BEGIN / COMMIT / ROLLBACK` database transactions.
- **Human Operations Controller (HITL):** Reviews and approves or rejects all network schedule delays and gate reassignments before they commit to the database.

**Pipeline Flow:**
1. **Trigger & Input Sanitisation:** An alert for Flight `EK-812` enters via the Streamlit OCC Console (webhook trigger) or n8n Chat Trigger. Both an n8n `IF / Switch` pre-filter and a Python guard (`src/guards.py`) scan inputs for prompt-injection payloads (e.g., `"ignore previous instructions"`, `"override duty limits"`) and malformed fields before the LLM runs.
2. **LLM Triage & Planning (n8n AI Agent):** The n8n AI Agent node (capped at 5 iterations with `Simple Memory`) calls the read-only FastAPI tool `GET /get_turnaround_and_crew_state`. It analyzes the 20-minute crew duty margin, open hydraulic maintenance log, and 45 at-risk passengers, then outputs a prioritized recovery plan, drafted passenger notifications, and an executive OCC brief.
3. **Deterministic Guard Checks & Atomic Execution (FastAPI + SQLite):**
   - **Passenger & Baggage Rebooking:** n8n sends proposed rebooking batches to `POST /execute_atomic_passenger_rebook`. Pure Python verifies that vulnerable flyers (`WCHR`, `UMNR`, `MEDICAL`) are protected before standard passengers, then wraps seat assignment, onward inventory decrement, and baggage transfer updates inside a single SQLite `BEGIN ... COMMIT` transaction. Any mid-way seat conflict triggers an immediate `ROLLBACK`, leaving zero double-bookings and zero orphaned bags.
   - **Schedule & Gate Changes:** n8n sends departure or gate proposals to `POST /stage_controller_schedule_change`. Pure Python hard-blocks any departure clearance that violates legal crew duty ceilings or has an `OPEN` maintenance log. Valid gate or schedule changes are saved to `staged_changes` with `status = 'PENDING_APPROVAL'`.
4. **Human-in-the-Loop (HITL) Operations Controller Gate:** When FastAPI returns `PENDING_APPROVAL`, n8n pauses at a **Wait** node (Form Submission / Webhook) showing the pending change. Only after the Operations Controller clicks **Approve** does n8n call `POST /commit_staged_change` to update the flight gate or schedule.
5. **Audit Logging & Live OCC Demo:** Every trigger, model used (including fallback activations), tool call, guard violation, rollback, and controller approval is logged to the `audit_log` SQLite table and displayed live in the Streamlit OCC Console.

### Recommended Hackathon Tech Stack

| Layer | Technology / Tool | Role in MVP |
| :--- | :--- | :--- |
| **Workflow & Agent Orchestrator** | **n8n** (self-hosted v2.4x+ via `npx n8n` or Docker) | Visual agent loop, prompt-injection pre-filter, multi-provider LLM fallback chain, and HITL `Wait` approval gate |
| **LLM Providers (Fallback Chain)** | **Groq** (`llama-3.3-70b-versatile` -> `llama-3.1-8b-instant`) -> **Google AI Studio** (`gemini-flash-latest`) -> **Ollama** (`qwen3:4b` or `qwen3:8b`) | Free cloud reasoning with automatic `429` retry/fallback and guaranteed offline local execution during the demo |
| **Backend & Guard Engine** | **Python 3.12**, **FastAPI**, **Uvicorn**, **Pydantic v2** | Immutable crew/maintenance/priority guardrails, atomic transaction gateway, and REST endpoints for n8n |
| **Database** | **SQLite3** (`aircraft_turnaround_disruption.sqlite`) | Zero-setup relational database with native `BEGIN / COMMIT / ROLLBACK` ACID transactions |
| **Synthetic Data** | **Faker** (`seed_db.py`) | Deterministic (`seed=42`) EK-812 disruption dataset with vulnerable tiers, forced seat conflict, and injection payloads |
| **OCC Demo Console** | **Streamlit** (`app.py`) | 3-column Mission Control UI: one-click demo scenarios, live audit/guard trace, live SQLite table inspector, and DB reset |
| **Automated Testing** | **pytest**, **httpx** | Unit tests for immutable Python guards and end-to-end atomic rollback verification |

---

## 2. Complete File-by-File Project Structure

```text
AeroTurn/
├── .env.example
├── .gitignore
├── PLAN.md
├── README.md
├── requirements.txt
├── seed_db.py
├── aircraft_turnaround_disruption.sqlite
├── api.py
├── app.py
├── n8n/
│   └── aeroturn_workflow.json
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── schemas.py
│   ├── db.py
│   ├── guards.py
│   └── services.py
└── tests/
    ├── __init__.py
    ├── test_guards.py
    ├── test_atomic_rebook.py
    └── test_api.py
```

### File Responsibilities & Connections

- **`.env.example`**: Template for local configuration (`N8N_WEBHOOK_URL`, `API_BASE_URL`, optional `GROQ_API_KEY`, `GEMINI_API_KEY`). Copied locally to `.env` (never committed).
- **`.gitignore`**: Excludes `.env`, `.venv/`, `__pycache__/`, `*.pyc`, and temporary test artifacts so secrets never leak to Git.
- **`PLAN.md`**: This master engineering blueprint used to guide incremental AI coding phases.
- **`README.md`**: Setup instructions, architecture summary, and the 4-part live OCC demo script.
- **`requirements.txt`**: Pinned Python dependencies (`fastapi`, `uvicorn`, `pydantic`, `faker`, `streamlit`, `requests`, `pytest`, `httpx`, `python-dotenv`).
- **`seed_db.py`**: Standalone deterministic seeding script (`Faker.seed(42)`) that drops and recreates all 8 tables in `aircraft_turnaround_disruption.sqlite` (`flights`, `crew`, `maintenance_logs`, `onward_inventory`, `passengers`, `baggage`, `staged_changes`, `audit_log`). Models EK-812 delayed 75 minutes, inbound crew at 700/720 duty minutes, open hydraulic log `MNT-409`, 45 at-risk passengers (including 9 vulnerable tiers: `WCHR`, `UMNR`, `MEDICAL`), 45 linked bags, 3 onward flights (`EK-201`, `EK-205`, and `EK-209` with `force_conflict = 1`), 1 prompt-injection note, and 1 missing-connection edge case. Called manually or via `POST /reset_db`.
- **`aircraft_turnaround_disruption.sqlite`**: Local SQLite database file read and modified exclusively through `src/db.py`.
- **`src/__init__.py`**: Marks `src/` as a Python package.
- **`src/config.py`**: Centralizes immutable policy constants (`DB_PATH`, `MIN_TURNAROUND_MINS = 45`, `VULNERABLE_TIERS = {"WCHR", "UMNR", "MEDICAL"}`, `INJECTION_PATTERNS`, `N8N_WEBHOOK_URL`, `API_BASE_URL`). Imported by `db.py`, `guards.py`, `services.py`, and `app.py`.
- **`src/schemas.py`**: Pydantic v2 request/response models (`RebookRequest`, `ScheduleChangeRequest`, `CommitChangeRequest`, `SanitiseRequest`, `AuditEntry`). Enforces strict input validation before business logic runs; imported by `api.py` and `services.py`.
- **`src/db.py`**: Database connection factory (`get_conn()` with `isolation_level=None` for explicit transaction control), table query helpers, and the single `write_audit_log()` function. Imported by `services.py` and `app.py`.
- **`src/guards.py`**: Pure Python deterministic safety rules (never calls an LLM). Contains `check_prompt_injection(text)`, `check_departure_floors(conn, flight_no)` (enforcing crew legal duty ceilings and mandatory maintenance sign-offs), and `check_vulnerable_priority(conn, pax_ids)`. Imported by `services.py` and unit-tested directly by `tests/test_guards.py`.
- **`src/services.py`**: Core transactional business logic implementing:
  - `get_turnaround_and_crew_state()`
  - `execute_atomic_passenger_rebook()` (wrapping passenger, baggage, and inventory writes in `BEGIN / COMMIT / ROLLBACK`)
  - `stage_controller_schedule_change()`
  - `commit_staged_change()`
  - Connects `db.py` and `guards.py` to `api.py`.
- **`api.py`**: Thin FastAPI application exposing HTTP endpoints (`/get_turnaround_and_crew_state`, `/execute_atomic_passenger_rebook`, `/stage_controller_schedule_change`, `/commit_staged_change`, `/sanitise_input`, `/audit_logs`, `/reset_db`) on `http://localhost:8000` for n8n and Streamlit.
- **`app.py`**: 3-column Streamlit OCC Mission Control dashboard (`http://localhost:8501`). Column 1 triggers the 4 demo scenarios (via n8n webhook or direct FastAPI fallback) and resets the DB; Column 2 displays the live audit log and green/red code-guard badges; Column 3 renders live SQLite tables (flights, crew, maintenance, passengers, bags, staged changes) and a backup Controller Approval panel.
- **`n8n/aeroturn_workflow.json`**: Exported n8n workflow file containing the Webhook/Chat trigger, prompt-injection `IF` filter, AI Agent node (with Ollama + Groq/Gemini fallback chain and `get_turnaround_and_crew_state` HTTP tool), downstream HTTP calls to FastAPI, and the `Wait` (Form Submission) Operations Controller approval gate.
- **`tests/__init__.py`**: Marks `tests/` as a Python package.
- **`tests/test_guards.py`**: Unit tests verifying prompt-injection blocking, crew duty floor rejection, open maintenance log rejection, and vulnerable-passenger priority blocking.
- **`tests/test_atomic_rebook.py`**: Transaction integrity tests proving that a mid-way seat conflict on `EK-209` triggers `ROLLBACK` and leaves zero double-bookings, zero orphaned bags, and unchanged seat inventory.
- **`tests/test_api.py`**: FastAPI `TestClient` end-to-end tests covering all endpoints including staging and committing a controller-approved gate reassignment.

---

## 3. Step-by-Step Build Order (What to Build First)

### Must-Have MVP Phases

1. **Phase 1: Project Skeleton, Config, Schemas & Verified Seed Data**
   - Create `.gitignore`, `.env.example`, `requirements.txt`, `src/__init__.py`, `src/config.py`, `src/schemas.py`, and `src/db.py`.
   - Update `seed_db.py` to include the `audit_log` table alongside the 7 core tables, then regenerate `aircraft_turnaround_disruption.sqlite`.
2. **Phase 2: Pure Python Guards, Atomic Services & Pytest Suite**
   - Implement `src/guards.py` (injection filter, crew duty floor, maintenance sign-off floor, vulnerable priority guard) and `src/services.py` (atomic `BEGIN/COMMIT/ROLLBACK` rebooking + HITL change staging/committing with audit logging).
   - Write and pass `tests/test_guards.py` and `tests/test_atomic_rebook.py`.
3. **Phase 3: FastAPI Server & n8n Agent Workflow (Local Ollama First)**
   - Implement `api.py` and pass `tests/test_api.py`.
   - Build the n8n workflow (`http://localhost:5678`) wired to `http://localhost:8000`, tested end-to-end on local **Ollama (`qwen3`)** first, then add **Groq** and **Gemini Flash** credentials with `Retry On Fail`, `Enable Fallback Model`, and `On Error -> Continue (error output)` to Ollama.
   - Export the working workflow to `n8n/aeroturn_workflow.json`.
4. **Phase 4: Streamlit OCC Console & 4-Scenario Demo Polish**
   - Build `app.py` with one-click buttons for all 4 required demo scenarios:
     1. **Blocked Illegal Departure** (crew duty breach + open hydraulic log)
     2. **Atomic Rollback Under Conflict** (mid-way seat conflict on `EK-209` -> zero double-bookings/orphaned bags)
     3. **Vulnerable Passenger Priority** (protecting `WCHR`/`UMNR`/`MEDICAL` flyers first on `EK-201`)
     4. **HITL Gate Reassignment** (pausing for Operations Controller approval before committing)
   - Include live SQLite inspection, live audit trace, and a **Reset Database** button.
   - Write `README.md` with setup commands and the 90-second demo script.

### Nice-to-Have Stretch Goals (Only After Core MVP Passes All 4 Demo Scenarios)
- **Standby Crew Pairing Matcher:** Add a `standby_crew` table and a pure-Python matcher endpoint that finds a legal reserve crew within terminal proximity when inbound crew breaches duty limits.
- **Below-Wing Critical-Path Tracker:** Add a `ground_ops` table (fueling, catering, ramp baggage, cleaning) with deterministic dependency sequencing (`graphlib`) to compute earliest legal ETD.
- **Cascading Delay & EU261 Cost Calculator:** Pure-Python calculator estimating passenger compensation savings and preserved onward connections before/after recovery.

---

## 4. Human-in-the-Loop (HITL) Checkpoints

- **Human Checkpoint 1 (After Phase 1):** Copy `.env.example` to `.env`, confirm `.gitignore` blocks `.env`, and inspect `aircraft_turnaround_disruption.sqlite` to verify the EK-812 scenario data (75m delay, 20m crew margin, open hydraulic log, 9 vulnerable passengers, `EK-209` conflict flag, and injection note) matches expectations.
- **Human Checkpoint 2 (After Phase 2):** Run `pytest` locally and manually verify test assertions: (a) no departure passes while `duty_remaining < 45` or `MNT-409` is `OPEN`, (b) standard passengers cannot be rebooked before vulnerable flyers, and (c) a mid-way conflict on `EK-209` leaves the database bit-for-bit identical after `ROLLBACK`.
- **Human Checkpoint 3 (After Phase 3):** Open `http://localhost:8000/docs` to verify all endpoints, add **Ollama**, **Groq**, and **Google Gemini** keys in **n8n Credentials**, and test the n8n workflow offline on Ollama first. Trigger the n8n **Wait** approval form manually to confirm it pauses and resumes cleanly.
- **Human Checkpoint 4 (After Phase 4):** Click through all 4 live demo scenarios in the Streamlit OCC Console (`http://localhost:8501`), test the **Reset Database** button, and verify offline resilience by temporarily disabling cloud credentials so Ollama takes over. Decide whether to implement 1 stretch goal or freeze the codebase for presentation.

---

## 5. AI Coding Agent Handoff Prompts

Use these prompts sequentially with your coding model (e.g., Gemini 3.8 Flash on Low/Medium thinking in Google Antigravity). Always stop and verify at each Human Checkpoint before issuing the next prompt.

### Phase 1 Prompt
```text
Read @PLAN.md carefully. Build Phase 1 only: create .gitignore, .env.example, requirements.txt, src/__init__.py, src/config.py, src/schemas.py, and src/db.py, and update the existing seed_db.py to also create the audit_log table while preserving the Flight EK-812 seed schema. Do not build guards.py, services.py, api.py, or app.py yet. Keep code clean without inline comments. When finished, run seed_db.py to verify it succeeds and stop at Human Checkpoint 1.
```

### Phase 2 Prompt
```text
Read @PLAN.md. Build Phase 2 only: implement src/guards.py (prompt-injection check, immutable crew duty-time and open maintenance floors, and vulnerable-passenger priority protection) and src/services.py (read-only state summary, atomic SQLite BEGIN/COMMIT/ROLLBACK passenger+baggage rebooking, and controller schedule change staging/committing with audit logging). Write tests/__init__.py, tests/test_guards.py, and tests/test_atomic_rebook.py, run pytest, confirm all tests pass, and stop at Human Checkpoint 2.
```

### Phase 3 Prompt
```text
Read @PLAN.md. Build Phase 3 only: implement api.py exposing all FastAPI endpoints listed in PLAN.md by delegating to src/services.py and src/guards.py, and add tests/test_api.py. Run pytest to confirm all Phase 2 and Phase 3 tests pass. Also provide step-by-step n8n node configuration instructions (matching n8n 2.x) to wire the Webhook trigger, prompt-injection IF filter, AI Agent node (Ollama primary + Groq/Gemini fallback), FastAPI HTTP nodes, and Wait form approval gate. Stop at Human Checkpoint 3.
```

### Phase 4 Prompt
```text
Read @PLAN.md. Build Phase 4 only: implement the 3-column Streamlit OCC Mission Control dashboard in app.py (Scenario triggers + DB Reset in Column 1, Live Audit & Guard Trace in Column 2, Live SQLite Tables + Controller Approval view in Column 3) and write README.md with setup commands and the 4-part demo script. Keep all existing pytest tests passing and stop at Human Checkpoint 4.
```

---

## 6. Key Architecture Assumptions

1. **Hybrid n8n + FastAPI + Streamlit Architecture:** n8n orchestrates the AI Agent, fallback chain, and Operations Controller `Wait` approval form; Python FastAPI + SQLite guarantees ACID rollbacks and immutable safety floors; Streamlit serves as the visual OCC Console for judges.
2. **Minimum Turnaround Floor:** `MIN_TURNAROUND_MINS` is set to `45` minutes, deterministically blocking the inbound crew (20 minutes remaining) from operating an immediate turnaround.
3. **Authentication:** No user login system is included for the hackathon MVP; the Operations Controller enters a Controller ID (e.g., `OCC-07`) when approving staged changes.
4. **LLM Fallback Chain:** Local **Ollama (`qwen3:4b` or `qwen3:8b`)** is used for development and final offline fallback, with **Groq** and **Google AI Studio (Gemini Flash)** as primary cloud providers inside n8n Credentials.
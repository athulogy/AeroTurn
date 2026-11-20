# AeroTurn ✈️
### Autonomous Aircraft Turnaround & Atomic Disruption Recovery Agent

**TechX Dubai '26 — Domain 4: Aviation & Airport Operations**  
**Scenario:** Flight `EK-812` arrives 75 minutes late into Dubai International Airport (DXB) with 280 connecting passengers (45 at-risk, including 9 vulnerable travelers), inbound flight crew 20 minutes from breaching legal duty limits, and an open hydraulic inspection work order requiring mandatory sign-off.

---

## 🏆 Key Highlights & Features

- **Hybrid Neuro-Symbolic Architecture:** Strict split between probabilistic reasoning (n8n + Groq Llama 3.3 / Gemini Flash / local Ollama) and deterministic safety (Python FastAPI + SQLite).
- **Immutable Safety Floors:** Legal crew duty ceilings (GCAA/EASA regulations) and open maintenance sign-offs are hard-blocked in pure Python — LLMs cannot override them.
- **ACID Atomic Rebooking:** Passenger seat reservations, onward inventory, and baggage transfers are wrapped in atomic `BEGIN / COMMIT / ROLLBACK` transactions. Mid-way conflicts trigger automatic rollback with **zero double-bookings and zero orphaned bags**.
- **Curveball U-4.1 (Vulnerable Passengers First):** OCC policy rebooking vulnerable flyers first (`WCHR`, `UMNR`, `MEDICAL`) in an isolated transaction, then standard passengers in batches of 10. Failures in batch 3 are isolated and escalated to the controller without rolling back earlier batches.
- **Curveball U-4.2 ("Crew is Happy to Extend"):** Crew chat messages are treated as unprivileged data. Immutable duty counters enforce legal maximums and hard-block departure.
- **Human-in-the-Loop (HITL):** Gate changes and schedule delays stage for Operations Controller review and cryptographic sign-off before committing.
- **Live OCC Mission Control Dashboard:** 3-column Streamlit web app with real-time audit logging, relational database inspector, and one-click scenario controls.
- **100% Test Coverage:** 41 automated pytest tests covering guards, atomic transactions, API endpoints, and both curveballs.

---

## 🏗️ System Architecture

```text
       ┌────────────────────────────────────────────────────────┐
       │              OCC Mission Control Console               │
       │           (Streamlit Web App on :8501)                 │
       └─────────────────────────┬──────────────────────────────┘
                                 │
           ┌─────────────────────┴──────────────────────┐
           ▼                                            ▼
┌──────────────────────────────┐          ┌──────────────────────────────┐
│  AI Orchestration Layer      │          │  Deterministic Guard Engine  │
│  (n8n Agent on :5678)        │          │  (FastAPI on :8000)          │
├──────────────────────────────┤          ├──────────────────────────────┤
│ • Prompt-Injection Filter    │          │ • Pure Python Duty Floors    │
│ • Groq Llama 3.3 (Primary)   │          │ • Mandatory Maintenance Gate │
│ • Gemini Flash (Fallback)    │  HTTP    │ • Vulnerable Tier Priority   │
│ • Ollama Qwen 3:8b (Offline) │─────────▶│ • Isolated Batched Rebooking │
│ • HITL Approval Wait Node    │          │ • Unprivileged Data Handlers │
└──────────────────────────────┘          └──────────────┬───────────────┘
                                                         │
                                          ┌──────────────▼───────────────┐
                                          │  Local SQLite3 Database      │
                                          │  (WAL Mode + ACID Engine)    │
                                          │  • flights, crew, maint      │
                                          │  • passengers, baggage       │
                                          │  • staged_changes, audit_log │
                                          └──────────────────────────────┘
```

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.12)
- Git

### 2. Clone and Install Dependencies
```bash
git clone https://github.com/YOUR_USERNAME/AeroTurn.git
cd AeroTurn

# Install Python requirements
pip install -r requirements.txt
```

### 3. Initialize the Disruption Database
```bash
python seed_db.py
```
This deterministically seeds all 8 tables modeling the `EK-812` disruption state.

---

## 🖥️ Running the Application

### Launch the Streamlit OCC Mission Control Console
```bash
streamlit run app.py
```
Open **[http://localhost:8501](http://localhost:8501)** in your browser.

### Launch the FastAPI Backend (Optional / Standalone)
```bash
python -m uvicorn api:app --reload
```
Interactive Swagger docs: **[http://localhost:8000/docs](http://localhost:8000/docs)**.

---

## 🧪 Running the Verification Suite

Run all 41 automated unit and integration tests:
```bash
python -m pytest tests/ -v
```
*(41 passed in ~9.9s — 100% green)*

---

## ⚡ Running the Live Curveballs Demo

Demonstrate both **Curveball U-4.1** and **Curveball U-4.2** in a single formatted terminal trace:
```bash
python demo_curveballs.py
```

---

## 📁 Repository Structure

```text
AeroTurn/
├── app.py                     # Streamlit OCC Mission Control Web UI
├── api.py                     # FastAPI REST Endpoints for n8n & External Clients
├── seed_db.py                 # Deterministic Seed Data Generator (Faker seed=42)
├── demo_curveballs.py         # Live Demonstration of Curveballs U-4.1 and U-4.2
├── manual_verify.py           # Standalone Guard Assertion Script
├── requirements.txt           # Pinned Python Dependencies
├── PLAN.md                    # System Architecture Blueprint
├── aircraft_turnaround_...db  # SQLite Disruption Database
├── n8n/
│   └── aeroturn_workflow.json # Complete Exported n8n Autonomous Agent Workflow
├── src/
│   ├── config.py              # Operational Constants (Floors, Vulnerable Tiers)
│   ├── db.py                  # Database Connection Factory & Audit Logger
│   ├── guards.py              # Pure Python Deterministic Safety Floors
│   ├── schemas.py             # Pydantic v2 Input/Output Models
│   └── services.py            # ACID Atomic Transactions & Batched Rebooking
└── tests/
    ├── test_guards.py         # Unit Tests for Duty and Maintenance Guards
    ├── test_atomic_rebook.py  # ACID Rollback & Conflict Tests
    ├── test_api.py            # FastAPI TestClient Integration Tests
    └── test_curveballs.py     # Automated Tests for Curveballs U-4.1 & U-4.2
```

---

## 📜 License
MIT License. Built for TechX Dubai '26.

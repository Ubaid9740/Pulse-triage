# Pulse

**Disaster warning, triage, and coordinated emergency dispatch — built to keep working with zero internet.**

*CODE//CONNECT'26 — Problem 01.*  
Architecture & System Design: [`System Design.pdf`](./System%20Design.pdf)

---

## Architecture Overview

```
                                      ┌────────────────────────────────────────┐
                                      │       Pulse Command Dashboard          │
                                      │         (React + Vite + Leaflet)       │
                                      │         Runs on Port 5173              │
                                      └──────────────────┬─────────────────────┘
                                                         │ REST / SSE
                                                         ▼
┌──────────────────────────┐  Sync / Packets  ┌────────────────────────────────────────┐
│     Pulse Mobile App     │ ◄──────────────► │           Pulse Server                 │
│ (React Native with Expo) │   (Ed25519 Signed│        (FastAPI + SQLite WAL)          │
│  Runs in Expo Go (8081)  │    X25519 Sealed)│         Runs on Port 8000              │
└────────────┬─────────────┘                  └──────────────────┬─────────────────────┘
             │                                                   │
             │ Phone-to-Phone Mesh                               │ Backup & Replay
             ▼                                                   ▼
┌──────────────────────────┐                  ┌────────────────────────────────────────┐
│     Nearby Field Phone   │                  │     Scenarios & Chaos Simulator        │
│ (Relays packets via QR)  │                  │       (Replay packs, Benchmarks)       │
└──────────────────────────┘                  └────────────────────────────────────────┘
```

| Component | Technology | Path | Description |
| :--- | :--- | :--- | :--- |
| **Server** | Python 3.11+, FastAPI, SQLite WAL | [`server/`](./server/) | Incident scoring engine, key authentication, packet ingestion, team tracking, and Silent Zone detection. |
| **Dashboard** | React 18, Vite, Leaflet | [`dashboard/`](./dashboard/) | Command post map, real-time case triage, dispatch suggestions, alert broadcasting, and resource tracking. |
| **Field App** | React Native, Expo SDK 57 | [`field/`](./field/) | Citizen & rescuer mobile app. Works 100% offline; passes packets phone-to-phone via QR mesh. |
| **Shared** | JSON Schemas, Multi-hazard profiles | [`shared/`](./shared/) | Contract specifications for flood, heat, earthquake, packets, and triage weights. |
| **Scenario** | Python simulation tools | [`scenario/`](./scenario/) | Automated scenario replay, synthetic load generator, and chaos testing suite. |

---

## System Requirements

- **Runtime:** Python 3.11+, Node.js 18+ (or 20+), Git.
- **Mobile Device:** Physical Android phone or iPhone running **Expo Go** (connected to the same local Wi-Fi / subnet).
- **Computer:** Windows, macOS, or Linux (laptop functions as the Command Post).

---

## Quick Start Guide

### 1. Backend Server (FastAPI)

```powershell
# Navigate to repo root and activate Python virtual environment
cd Pulse-triage
python -m venv server\.venv
.\server\.venv\Scripts\Activate.ps1

# Install requirements and start server
pip install -r server\requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir server --reload
```
- **API Status:** `http://localhost:8000/api/status`
- **Interactive Swagger Docs:** `http://localhost:8000/docs`
- **Setup QR Code:** `http://localhost:8000/api/setup-qr.png`

---

### 2. Command Dashboard (React + Vite)

Open a new terminal:
```powershell
cd Pulse-triage\dashboard
npm install
npm run dev
```
- Open **`http://localhost:5173`** in your browser.

---

### 3. Mobile Field App (React Native / Expo)

Open a third terminal:
```powershell
cd Pulse-triage\field
npm install
npx expo start -c
```
1. Open the **Expo Go** app on your phone.
2. Scan the terminal's QR code to load the app.

---

## Key Features

1. **Zero-Internet Operation & Offline Mesh:**
   - Every report is digitally signed (Ed25519) and sealed (X25519) locally on the device.
   - When offline, reports queue safely and can hop from phone to phone using dynamic QR-code packet hand-offs until a phone reaches connection.

2. **Role-Based Onboarding & Cryptographic Trust:**
   - **Helpers (Civilians):** Instant onboarding without setup requirements to submit emergency reports immediately.
   - **Volunteers & Rescue Teams:** Scan the Command Post setup QR to securely bind keys (`sign_pk`, `box_pk`), unlock team dispatch jobs, and stream live GPS location.

3. **Deterministic Multi-Hazard Triage:**
   - Dynamic priority scoring based on hazard profiles (flood, heat, earthquake).
   - Duplicate incident deduplication, confidence adjustments, and time-decay re-ranking.

4. **Silent Zone & Outreach Engine:**
   - Identifies severely impacted regions where zero reports have been received (Silent Zones).
   - Dispatches targeted welfare checks from the opt-in vulnerable resident registry.

---

## Running Tests

- **Backend Tests (245 test cases):**
  ```powershell
  cd server
  python -m pytest
  ```

- **Field App Core Crypto & Sync Tests:**
  ```powershell
  cd field
  $env:PT_TEST_SERVER="http://127.0.0.1:8000"; npm test
  ```

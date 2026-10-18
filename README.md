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
| **Server** | Python 3.11+, FastAPI, SQLite WAL | [`server/`](./server/) | Incident scoring engine, device key authentication, packet ingestion, team tracking, and Silent Zone detection. |
| **Dashboard** | React 18, Vite, Leaflet | [`dashboard/`](./dashboard/) | Command post map, real-time case triage, dispatch suggestions, alert broadcasting, and resource tracking. |
| **Field App** | React Native, Expo SDK 57 | [`field/`](./field/) | Citizen & rescuer mobile app with redesigned unified UI. Works 100% offline; relays packets phone-to-phone via QR mesh. |
| **Shared** | JSON Schemas, Multi-hazard profiles | [`shared/`](./shared/) | Contract specifications for flood, heat, earthquake, packets, and triage weights. |
| **Scenario** | Python simulation tools | [`scenario/`](./scenario/) | Automated scenario replay, synthetic load generator, and chaos testing suite. |

---

## Implemented Features & Capabilities

### 1. Security & Role-Based Onboarding
- **Helper Quick-Start:** Civilians and neighbors can immediately tap "Start as Helper" without scanning a QR code, utilizing fallback command-post public keys so reports can be submitted instantly during a disaster.
- **Volunteer & Rescue Team Authentication:** Volunteers and official rescue teams scan the Command Post setup QR code to securely bind signing keys (`sign_pk`) and box keys (`box_pk`), unlocking job assignments, welfare checks, and status streams.
- **Automated Device Trust & Scoring:**
  - When verified volunteer or rescue devices register, the server automatically flags them as `trusted = 1` in the database.
  - Incident reports originating from trusted devices automatically start with an elevated confidence score (**0.9** vs unverified **0.5**).

### 2. Mobile Field App (React Native / Expo)
- **High-Contrast Design System:** Unified design tokens (`T`, `RADIUS`, `TONES`), outdoor-legible surfaces, and danger/warning bands matching the command dashboard.
- **Native SVG Iconography:** Built-in vector stroke icon set without heavy third-party icon libraries.
- **Emergency Reporting:** Simplified report form with hazard selector, affected people stepper, special needs toggles, automatic GPS coordinate tagging with accuracy estimates, and landmark notes.
- **Cleaned Triage Feed:** Clean card design showing disaster type, location, and people count without distracting countdown timers.
- **Offline QR Mesh Network:**
  - Store-and-forward architecture with SQLite / AsyncStorage.
  - Generates rotating animated QR codes of encrypted packets for device-to-device transfers without internet, cellular, or Wi-Fi.
- **Safety & Crash Protection:** Top-level React `ErrorBoundary`, safe `SecureStore` fallbacks, and unsaved form leave guards.

### 3. Command Post Server (FastAPI + SQLite)
- **Deterministic Triage & Rescoring:**
  - Multi-hazard weighted scoring (flood, heat, earthquake) combining vulnerability, medical needs, and time elapsed.
  - Deduplication and report clustering: incoming reports from the same geohash location automatically merge into a single incident case with verifiable history.
- **Silent Zone & Vulnerable Outreach:**
  - Detects "Silent Zones" — severely impacted hazard regions from which zero reports have been received.
  - Cross-references opt-in vulnerable registries (elderly, mobility-impaired, oxygen-dependent) to automatically generate welfare-check tasks for field teams.
- **Cryptographic Packet Pipeline:**
  - End-to-end Ed25519 digital signatures and X25519 sealed box encryption.
  - Replay attack prevention and tampered packet rejection.
- **Live Dispatcher Operations:**
  - Interactive verification (`/verify`), case splitting (`/split`), manual priority overrides, and automated team recommendation based on distance and capabilities.

### 4. Interactive Dispatch Dashboard (React + Leaflet)
- **Live Incident Map:** Real-time visualization of active cases, severity markers, Silent Zones in red, and live rescuer team positions.
- **Emergency Alert Broadcasts:** Alert composer with multi-language support, automated evacuation point tagging, and text-to-speech loudspeaker announcements.
- **Resource & Stock Burn Tracking:** Monitors shelter capacity, medical supplies, fuel levels, and team availability statuses (Available, En Route, On Scene, Out of Service).

---

## System Requirements

- **Runtime:** Python 3.11+, Node.js 18+ (or 20+), Git, and PowerShell.
- **Mobile Device:** Physical Android phone or iPhone running **Expo Go** (connected to the same Wi-Fi / subnet).
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
- **API Health:** `http://localhost:8000/api/status`
- **Interactive Swagger Docs:** `http://localhost:8000/docs`
- **Setup QR Code:** `http://localhost:8000/api/setup-qr.png`

---

### 2. Command Dashboard (React + Vite)

Open a second terminal:
```powershell
cd Pulse-triage\dashboard
npm install
npm run dev
```
- Access Dashboard: **`http://localhost:5173`**

---

### 3. Mobile Field App (React Native / Expo)

Open a third terminal:
```powershell
cd Pulse-triage\field
npm install
npx expo start -c
```
1. Open the **Expo Go** app on your phone.
2. Scan the terminal's QR code to launch **Pulse**.

---

## Running Verification Tests

- **Backend Pytest Suite (245 tests):**
  ```powershell
  cd server
  python -m pytest
  ```

- **Field App Core Crypto & Mesh Protocol Tests:**
  ```powershell
  cd field
  $env:PT_TEST_SERVER="http://127.0.0.1:8000"; npm test
  ```

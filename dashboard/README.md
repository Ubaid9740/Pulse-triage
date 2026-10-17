# dashboard/: dispatcher dashboard (owner: C)

React + Vite + react-leaflet, plain CSS, built to static files that the server serves at `/`.

## Start (hour 0)

From the repo root:

```
npm create vite@latest dashboard -- --template react
cd dashboard
npm install
npm install leaflet react-leaflet protomaps-leaflet
```

(Vite may ask before writing into this folder because this README exists; let it continue.)

In `vite.config.js`, proxy the API to the server during development:

```js
server: { proxy: { "/api": "http://localhost:8000" } }
```

`npm run dev` while building; `npm run build` for the demo (the server then serves `dashboard/dist`).

## Data

Poll `GET /api/snapshot` every 2 s. Its shape is `shared/schemas/snapshot.schema.json`; a full example is
`shared/examples/snapshot.json`. To see real data, run the server and
`python server/scripts/send_example.py report report_heat`.

Build order and prompts: System Design 14.5 (C) and Team Brief 4.10 (C1, C2, C3).

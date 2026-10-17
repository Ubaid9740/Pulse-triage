# scenario/: demo packs, replay and simulation (owner: D)

Planned layout (System Design 14.1):

```
scenario/
  zones.geojson            8 to 10 named zones of the demo town (draw at geojson.io; each
                           feature needs "name" and "population"; shared/examples/zones.geojson)
  templates/               hand-written message templates per hazard
  packs/flood/ packs/heat/ packs/earthquake/
                           people.json registry.csv teams.json shelters.json supplies.json
                           windows.json messages.json
  generate.py              builds a pack from zones and templates (fixed random seed)
  replay.py                streams a pack into the server at a chosen speed
  simulate.py              first come first served vs PulseTriage chart
```

Packs are loaded by `server/scripts/reset_demo.py --pack <name>`. It reads `pack.json`
(`{"hazard": "flood", "hard_hit": [...]}`), `zones.geojson` (in the pack or in `scenario/`),
`registry.csv`, `shelters.json`, `teams.json` and `supplies.json`; the formats are in the
server README ("Demo reset, backups, revoking"). The other files are yours for generate.py and
replay.py.

Use the server venv (`pip install matplotlib shapely`). Until `replay.py` exists,
`python server/scripts/send_example.py report report_heat` puts example cases on the dashboard.

Build order and prompts: System Design 14.5 (D) and Team Brief 4.10 (D1, D2, D3).

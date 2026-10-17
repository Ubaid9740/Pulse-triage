# scenario/: demo packs, replay and simulation (owner: D)

The demo city is Karachi. `zones.geojson` holds 8 zones drawn roughly around real neighbourhoods
(Lyari, Saddar, Clifton, Korangi, Shah Faisal, Malir, Orangi Town, North Nazimabad). Their
populations are demo numbers, not census figures. Names, phone numbers and residents in the packs
are made up.

## Flood pack (`packs/flood/`)

A monsoon flood: the Lyari and Malir rivers overflow. Hard-hit: Lyari, Korangi and Shah Faisal.
Shah Faisal sends almost no reports, so it turns into a Silent Zone.

| File | What |
| --- | --- |
| `pack.json` | disaster and hard-hit zones |
| `registry.csv` | 23 opt-in residents (12 in Shah Faisal) |
| `shelters.json` | 4 shelters (Malir nearly full) and a hospital |
| `teams.json` | 2 boats, a truck, a medic, a rescue team, a welfare team |
| `supplies.json` | water, life jackets, fuel, blankets, first-aid kits |
| `reports.json` | 15 phone reports (two are about the same man, so they merge) |

```
python server/scripts/reset_demo.py --pack flood --keep-server
python scenario/demo_reports.py --pack flood
```

The reset reads `pack.json`, `zones.geojson` (in the pack or here), `registry.csv`,
`shelters.json`, `teams.json` and `supplies.json` (formats: server README, "Demo reset, backups,
revoking"). `demo_reports.py` signs and seals `reports.json` the way phones do; each demo phone
keeps the same key every run.

## Still to build (System Design 14.1)

```
  templates/               hand-written message templates per hazard
  packs/heat/ packs/earthquake/
  generate.py              builds a pack from zones and templates (fixed random seed)
  replay.py                streams a pack into the server at a chosen speed
  simulate.py              first come first served vs PulseTriage chart
```

Use the server venv (`pip install matplotlib shapely` for those). Build order and prompts:
System Design 14.5 (D) and Team Brief 4.10 (D1, D2, D3).

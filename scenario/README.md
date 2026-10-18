# scenario/: demo packs, replay and simulation (owner: D)

The demo city is Karachi. `zones.geojson` holds 8 zones drawn roughly around real neighbourhoods
(Lyari, Saddar, Clifton, Korangi, Shah Faisal, Malir, Orangi Town, North Nazimabad). Their
populations are demo numbers, not census figures. Every name, phone number (`+000 ...`), resident
and message in the packs is made up.

```
pip install -r scenario/requirements.txt         # matplotlib, for simulate.py (server venv)
python scenario/generate.py                      # builds packs/flood, packs/heat, packs/earthquake
python scenario/replay.py --pack flood           # reset the running server to the pack and play it
python scenario/simulate.py                      # the chart for the pitch: scenario/out/simulation.png
```

The dashboard's **Replay** button does the same as `replay.py`: pick a pack and a speed, Start.

## The packs (`generate.py`, fixed seed 7)

Built from `zones.geojson` and the hand-written messages in `templates/<hazard>.json` (short,
misspelt, the odd Urdu word, as people text in a panic; each with a hidden truth). Each message
gets a time, a place inside its zone and a sender; about a quarter get a duplicate within 150 m
and an hour from another phone, reworded. Each pack folder holds:

| File | What |
| --- | --- |
| `pack.json` | disaster, hard-hit zones at the start, story start time, default speed, alert zones |
| `registry.csv` | 200 opt-in vulnerable residents with conditions |
| `teams.json` | teams with start positions and a demo phone each (`device_id`), so the replay can move them |
| `shelters.json` | shelters, cooling centres and a hospital, with capacity and head count |
| `supplies.json` | starting stock and warning levels |
| `windows.json` | when each zone's window closes (also events in the story) |
| `messages.json` | the story: timed events (below) |
| `people.json` | the hidden truth (who needs help, how badly, by when); only `simulate.py` reads it |

| Pack | Story (scenario time) | Shows |
| --- | --- | --- |
| Flood, 14:00, 60x | Lyari and Korangi hard-hit; 14:10 issue the warning, replies start; 14:30 a burst of about 150 messages with duplicates; 15:00 towers fail in Shah Faisal (hard-hit, then silent); 15:15 Korangi causeway window; 15:30 fake stadium report; 15:45 wrong location; 15:50 Boat 3 stops; 16:00 internet cut; 16:25 oxygen down to 3 | Merging, ranking, Silent Zone, windows, fake guard, location check, overdue, offline banner, low stock |
| Heat, 07:00, 90x | Issue the heat warning for 4 zones; registered people reply, except in Orangi Town (silent); few messages; 10:15 a volunteer finds heatstroke; 11:00 hottest hours window; 11:30 Korangi cooling centre nearly full | Alerts and coverage, welfare checks from silence, heat scoring, places |
| Earthquake, 03:10, 60x | Saddar, Lyari, North Nazimabad hard-hit; towers down in North Nazimabad (silent); trapped people, gas, collapses; rain window; fake report | Third profile, rescue teams scarce, trade-off |

Story events (`messages.json`, played by `server/app/replay.py`): `report` (an app report signed
by that phone), `text` (SMS or mesh text, read by keywords then the AI), `reply` (to the newest
active alert; held until the presenter issues one), `window`, `hard_hit`, `chaos`, `ai_down`,
`team_stop`, `supply`, `place` and `cue` (a line for the presenter, shown in the bottom strip).
Messages arrive at the replay speed; hours left and windows run in real minutes. Scenario teams
move by themselves once assigned: "on my way", pings toward the case, on scene within 100 m,
done after 10 scenario minutes, back to base.

## The simulation (`simulate.py`)

Same situations, teams and travel times both ways: first come first served (people who never
report are never reached) against PulseTriage's points, with welfare checks for registered
people who did not answer. Both are judged by the hidden truth: was a team there before the
deadline? 20 seeds per pack. Our latest run (share of critical cases reached in time, mean and
range):

| Pack | First come, first served | PulseTriage |
| --- | --- | --- |
| Flood | 10% (6-17) | 24% (15-34) |
| Heat | 25% (15-41) | 31% (18-55) |
| Earthquake | 52% (36-67) | 57% (33-73) |

Simplifications: any team can serve any case; 20 minutes on scene. Always say "in our
simulation"; never present it as a real-world result.

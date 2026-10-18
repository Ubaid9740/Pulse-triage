// The phone's core against a real server (npm test). Start one with signatures and sealing
// required, e.g. from the repo root:
//   PT_REQUIRE_SIGNATURES=1 PT_REQUIRE_SEALING=1 PT_AI=off PT_PORT=8011 \
//     server/.venv/Scripts/python.exe -m uvicorn app.main:app --port 8011 --app-dir server
// and point PT_TEST_SERVER at it (default http://127.0.0.1:8011).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import nacl from "tweetnacl";
import util from "tweetnacl-util";
import { deviceIdFor, geohash, makeWire, newKeys, openSealed, parseBody, trustworthy } from "../src/core/packet.js";
import { hoursToCritical, urgencyHint } from "../src/core/rules.js";
import { PacketStore, memoryStorage } from "../src/core/store.js";
import { MeshSession, batches, fromQr, toQr } from "../src/core/mesh.js";
import { ServerLink } from "../src/core/sync.js";
import { reportPayload, alertReply, teamPing, volunteerSetup, ack } from "../src/core/payloads.js";

const SERVER = process.env.PT_TEST_SERVER || "http://127.0.0.1:8011";
const getJson = async (path) => (await fetch(SERVER + path)).json();
const postJson = async (path, body) =>
  (await fetch(SERVER + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();

const profiles = {
  common: JSON.parse(readFileSync(new URL("../../shared/profiles/common.json", import.meta.url))),
  profiles: { flood: JSON.parse(readFileSync(new URL("../../shared/profiles/flood.json", import.meta.url))) },
};

async function phone(role = "helper") {
  const keys = newKeys();
  const setup = await getJson("/api/setup-qr");
  const device = deviceIdFor(keys.publicKey);
  const store = new PacketStore(memoryStorage());
  const link = new ServerLink({ store, settings: { servers: [SERVER], sign_pk: setup.sign_pk, device } });
  return { keys, setup, device, store, link, role };
}

function house14(p, lat = 24.8702, lng = 67.0008) {
  const payload = reportPayload({ hazard: "flood", forWhom: "neighbour", people: 1,
    conditions: ["elderly", "cannot_walk", "oxygen", "alone"], details: { water: "waist", rising: true },
    note: "Old man alone, oxygen half empty", lat, lng, accuracy: 12, landmark: "house 14, Chakiwara",
    role: p.role });
  const urgency = urgencyHint(profiles, "flood", payload.details, payload.conditions);
  return makeWire("report", payload, { device: p.device, keys: p.keys, boxPk: p.setup.box_pk, urgency,
    area: geohash(lat, lng) });
}

test("geohash and rules match the server", () => {
  assert.equal(geohash(0, 0), "s0000");
  assert.equal(geohash(24.8702, 67.0008), "tkrtk");          // server/app/packets.py gives the same
  const h = hoursToCritical(profiles, "flood", { water: "waist", rising: true }, ["elderly"]);
  assert.equal(h.hours, 2);
  assert.equal(urgencyHint(profiles, "flood", { water: "chest" }, []), 2);           // 1 h: "under 1 h" is 3
  assert.equal(urgencyHint(profiles, "flood", {}, []), 0);
});

test("a sealed box opens with the matching key, and signatures catch tampering", () => {
  const box = nacl.box.keyPair();
  const keys = newKeys();
  const wire = makeWire("report", { hello: "Karachi" }, { device: "dev_T1", keys,
    boxPk: util.encodeBase64(box.publicKey) });
  const body = parseBody(wire);
  assert.equal(openSealed(util.encodeBase64(box.publicKey), util.encodeBase64(box.secretKey), body.sealed), '{"hello":"Karachi"}');
  assert.ok(trustworthy(wire, null));
  assert.ok(!trustworthy({ ...wire, body: wire.body.replace("dev_T1", "dev_T2") }, null));
});

test("a report goes straight to the server when it is reachable", async () => {
  const p = await phone();
  const wire = house14(p);
  p.store.add(wire, { mine: true });
  const out = await p.link.syncOnce();
  assert.equal(out.online, true);
  assert.equal(out.uploaded, 1, JSON.stringify(out));
  assert.equal(p.store.counts().waiting, 0);
  const snap = await getJson("/api/snapshot");
  assert.ok(snap.cases.some((c) => c.landmark === "house 14, Chakiwara"));
});

test("an offline phone's report walks to the server through another phone", async () => {
  const a = await phone();                       // no signal: it never talks to the server
  const b = await phone();
  const wire = house14(a, 24.8711, 67.0019);
  a.store.add(wire, { mine: true });
  // A meets B: run the protocol over an in-memory link both ways.
  const queueA = [];
  const queueB = [];
  const sa = new MeshSession({ store: a.store, send: (m) => queueB.push(m), device: a.device, role: "helper", commandPostKey: a.setup.sign_pk });
  const sb = new MeshSession({ store: b.store, send: (m) => queueA.push(m), device: b.device, role: "helper", commandPostKey: b.setup.sign_pk });
  sa.start();
  sb.start();
  for (let i = 0; i < 20 && (queueA.length || queueB.length); i++) {
    while (queueB.length) sb.onMessage(JSON.parse(JSON.stringify(queueB.shift())));
    while (queueA.length) sa.onMessage(JSON.parse(JSON.stringify(queueA.shift())));
  }
  assert.ok(sa.finished && sb.finished);
  assert.equal(sb.received, 1);
  const carried = b.store.valid()[0];
  assert.equal(carried.wire.hops, 1);
  const out = await b.link.syncOnce();             // B reaches the server and hands it over
  assert.equal(out.uploaded, 1, JSON.stringify(out));
  const detail = await getJson("/api/snapshot");
  assert.ok(detail.cases.some((c) => c.landmark === "house 14, Chakiwara"));
});

test("alerts from the command post arrive, verified; forged ones are dropped", async () => {
  const p = await phone();
  const until = new Date(Date.now() + 6 * 3600e3).toISOString();
  const zones = (await getJson("/api/zones")).zones.map((z) => z.name).slice(0, 1);
  const issued = await postJson("/api/alerts", { hazard: "flood", severity: "warning", zones, valid_until: until });
  assert.ok(issued.alert_id, JSON.stringify(issued));
  await p.link.syncOnce();
  const alert = p.store.bodies("alert").find((b) => b.public.alert_id === issued.alert_id);
  assert.ok(alert, "the alert reached the phone");
  // A forged alert (someone else's key) never gets in.
  const fake = makeWire("report", {}, { device: "command_post", keys: newKeys() });
  const forged = { ...fake, body: fake.body.replace('"kind":"report"', '"kind":"alert"') };
  assert.ok(!trustworthy(forged, p.setup.sign_pk));
  // Reply "I'm safe".
  const reply = makeWire("alert_reply", alertReply({ alertId: issued.alert_id, status: "safe", lat: 24.87, lng: 67.0 }),
    { device: p.device, keys: p.keys, boxPk: p.setup.box_pk, urgency: 1 });
  p.store.add(reply, { mine: true });
  const out = await p.link.syncOnce();
  assert.equal(out.uploaded, 1, JSON.stringify(out));
});

test("a team phone joins, gets its job and reports back", async () => {
  const p = await phone("rescue_team");
  const lat = 24.8645;
  const lng = 67.0105;
  const join = makeWire("volunteer", volunteerSetup({ name: "Boat 7", role: "rescue_team", teamType: "boat",
    skills: ["boat"], lat, lng }), { device: p.device, keys: p.keys, boxPk: p.setup.box_pk, urgency: 2 });
  p.store.add(join, { mine: true });
  assert.equal((await p.link.syncOnce()).uploaded, 1);
  const team = (await getJson("/api/teams")).teams.find((t) => t.device_id === p.device);
  assert.ok(team, "the server made a team for this phone");
  const target = (await getJson("/api/snapshot")).cases.find((c) => c.lat !== null);
  const assigned = await postJson("/api/assign", { case_id: target.id, team_id: team.id, reassign: true });
  assert.ok(assigned.job_id, JSON.stringify(assigned));
  await p.link.syncOnce();
  const job = p.store.bodies("job").find((b) => b.public.job_id === assigned.job_id);
  assert.ok(job && job.to_device === p.device, "the signed job reached this phone");
  const send = (kind, payload, extra = {}) => p.store.add(makeWire(kind, payload,
    { device: p.device, keys: p.keys, boxPk: p.setup.box_pk, urgency: 2, ...extra }), { mine: true });
  send("ack", ack({ teamId: team.id, jobId: assigned.job_id, status: "en_route" }));
  send("team_ping", teamPing({ teamId: team.id, lat: target.lat, lng: target.lng, status: "en_route",
    caseId: target.id, battery: 80, fuel: "full" }), { replaceKey: `ping:${team.id}` });
  assert.equal((await p.link.syncOnce()).uploaded, 2);
  const after = (await getJson("/api/teams")).teams.find((t) => t.id === team.id);
  assert.equal(after.status, "on_scene", "the ping within 100 m put the team on scene");
  send("ack", ack({ teamId: team.id, jobId: assigned.job_id, status: "done", outcome: { people_helped: 1, taken_to: "stayed", supplies_used: {} } }));
  await p.link.syncOnce();
  const done = (await getJson("/api/teams")).teams.find((t) => t.id === team.id);
  assert.equal(done.status, "returning");
});

test("the store keeps only the newest ping and QR hand-off round-trips", () => {
  const keys = newKeys();
  const store = new PacketStore(memoryStorage());
  const ping = (t) => makeWire("team_ping", { team_id: "b", lat: 1, lng: 1, at: "x", status: "available" },
    { device: "dev_T1", keys, replaceKey: "ping:b", created: t });
  store.add(ping(Date.now() - 60000));
  store.add(ping(Date.now()));
  assert.equal(store.valid().length, 1);
  const wire = store.valid()[0].wire;
  assert.deepEqual(fromQr(toQr(wire)), wire);
  assert.equal(batches(Array(50).fill(wire), 5000).length > 1, true);
});

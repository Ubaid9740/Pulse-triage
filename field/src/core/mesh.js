// The phone-to-phone protocol (System Design 4.4), independent of the transport that carries it
// (Nearby Connections in a development build, or QR codes in Expo Go):
//   {"t":"hello","device","role","v":1}   {"t":"have","ids":[...]}   {"t":"want","ids":[...]}
//   {"t":"packets","items":[wire,...]}  (batches under 30 KB)        {"t":"done"}
// Received packets are checked (signature, expiry, hops) and stored with hops + 1.
import { trustworthy } from "./packet.js";

export const BATCH_BYTES = 30000;

export function batches(wires, maxBytes = BATCH_BYTES) {
  const out = [];
  let current = [];
  let size = 0;
  for (const w of wires) {
    const n = JSON.stringify(w).length;
    if (current.length && size + n > maxBytes) {
      out.push(current);
      current = [];
      size = 0;
    }
    current.push(w);
    size += n;
  }
  if (current.length) out.push(current);
  return out;
}

// Take packets from another phone. Returns how many were new.
export function receive(store, wires, { commandPostKey, allowUnsigned = false, now = Date.now() } = {}) {
  let added = 0;
  for (const wire of wires) {
    if (!wire || typeof wire.body !== "string") continue;
    if (!trustworthy(wire, commandPostKey, { allowUnsigned })) continue;
    if (store.add({ ...wire, hops: (wire.hops || 0) + 1 }, { now }).added) added += 1;
  }
  return added;
}

export class MeshSession {
  // send(message) delivers one JSON message to the peer.
  constructor({ store, send, device, role, commandPostKey, allowUnsigned = false }) {
    Object.assign(this, { store, send, device, role, commandPostKey, allowUnsigned });
    this.received = 0;
    this.sent = 0;
    this.peerDone = false;
    this.selfDone = false;
  }

  start() {
    this.send({ t: "hello", device: this.device, role: this.role, v: 1 });
    this.send({ t: "have", ids: this.store.valid().map((r) => r.id) });
  }

  onMessage(m) {
    if (!m || typeof m !== "object") return;
    if (m.t === "hello") this.peer = m.device;
    else if (m.t === "have") this.send({ t: "want", ids: (m.ids || []).filter((id) => !this.store.has(id)) });
    else if (m.t === "want") {
      const wanted = new Set(m.ids || []);
      const wires = this.store.valid().filter((r) => wanted.has(r.id)).map((r) => r.wire);
      for (const batch of batches(wires)) this.send({ t: "packets", items: batch });
      this.sent += wires.length;
      this.selfDone = true;
      this.send({ t: "done" });
    } else if (m.t === "packets") {
      this.received += receive(this.store, m.items || [], this);
    } else if (m.t === "done") this.peerDone = true;
  }

  get finished() {
    return this.peerDone && this.selfDone;
  }
}

// QR hand-off: one packet per code ("PT1:" + wire JSON), for phones with no other link.
export const QR_PREFIX = "PT1:";
export const toQr = (wire) => QR_PREFIX + JSON.stringify(wire);
export function fromQr(text) {
  if (typeof text !== "string" || !text.startsWith(QR_PREFIX)) return null;
  try {
    return JSON.parse(text.slice(QR_PREFIX.length));
  } catch {
    return null;
  }
}

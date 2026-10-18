// The phone's packet store (System Design 4.3): every packet this phone made or carries.
//   - never delete a packet this phone made until the server has it
//   - drop relayed packets once they expire
//   - keep only the newest packet per replace_key (team pings, alert updates)
//   - cap the store, evicting the oldest low-urgency relayed packets first
// storage is AsyncStorage-like ({ getItem, setItem }); tests pass an in-memory one.
import { parseBody } from "./packet.js";

export const STORE_MAX = 600;          // AsyncStorage keeps one value: stay well under its size limits
const KEY = "pt.packets.v1";

export class PacketStore {
  constructor(storage, max = STORE_MAX) {
    this.storage = storage;
    this.max = max;
    this.items = new Map();            // id -> record
    this.listeners = new Set();
  }

  async load() {
    const raw = await this.storage.getItem(KEY);
    this.items = new Map();
    for (const rec of raw ? JSON.parse(raw) : []) this.items.set(rec.id, rec);
    this.prune();
  }

  async save() {
    await this.storage.setItem(KEY, JSON.stringify([...this.items.values()]));
    this.listeners.forEach((fn) => fn());
  }

  onChange(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  has(id) {
    return this.items.has(id);
  }

  // Add a packet. Returns {added: bool, reason}. Relayed packets arrive with their hops already +1.
  add(wire, { mine = false, now = Date.now() } = {}) {
    const body = parseBody(wire);
    if (!body) return { added: false, reason: "unreadable" };
    if (this.items.has(body.id)) return { added: false, reason: "duplicate" };
    if (Date.parse(body.expires_at) <= now) return { added: false, reason: "expired" };
    if (!mine && wire.hops > body.max_hops) return { added: false, reason: "too_many_hops" };
    if (body.replace_key) {
      for (const rec of this.items.values()) {
        if (rec.replace_key !== body.replace_key || rec.kind !== body.kind) continue;
        if (Date.parse(rec.created_at) >= Date.parse(body.created_at)) return { added: false, reason: "older" };
        this.items.delete(rec.id);
      }
    }
    this.items.set(body.id, {
      id: body.id, wire, kind: body.kind, urgency: body.urgency, created_at: body.created_at,
      expires_at: body.expires_at, replace_key: body.replace_key || null, to_device: body.to_device || null,
      mine, delivered: false, received_at: new Date(now).toISOString(),
    });
    this.evict();
    return { added: true };
  }

  evict() {
    if (this.items.size <= this.max) return;
    const removable = [...this.items.values()]
      .filter((r) => !r.mine || r.delivered)
      .sort((a, b) => a.urgency - b.urgency || Date.parse(a.created_at) - Date.parse(b.created_at));
    for (const rec of removable) {
      if (this.items.size <= this.max) break;
      this.items.delete(rec.id);
    }
  }

  prune(now = Date.now()) {
    for (const rec of [...this.items.values()]) {
      if (Date.parse(rec.expires_at) <= now && (!rec.mine || rec.delivered)) this.items.delete(rec.id);
    }
  }

  // Valid, unexpired packets, highest urgency first, then newest.
  valid(now = Date.now()) {
    return [...this.items.values()]
      .filter((r) => Date.parse(r.expires_at) > now)
      .sort((a, b) => b.urgency - a.urgency || Date.parse(b.created_at) - Date.parse(a.created_at));
  }

  // What the server still needs: anything a phone made (ours or relayed) that it has not confirmed.
  waiting() {
    return this.valid().filter((r) => !r.delivered && !["alert", "job", "revoke"].includes(r.kind));
  }

  markDelivered(ids, note = null) {
    for (const id of ids) {
      const rec = this.items.get(id);
      if (rec) {
        rec.delivered = true;
        if (note) rec.note = note;
      }
    }
  }

  bodies(kind) {
    return this.valid()
      .filter((r) => r.kind === kind)
      .map((r) => ({ ...parseBody(r.wire), _received_at: r.received_at }));
  }

  counts() {
    const all = [...this.items.values()];
    return { total: all.length, waiting: this.waiting().length, mine: all.filter((r) => r.mine).length };
  }
}

export function memoryStorage() {
  const map = new Map();
  return { getItem: async (k) => map.get(k) ?? null, setItem: async (k, v) => void map.set(k, v) };
}

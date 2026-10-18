// Talking to the command post when it can be reached (System Design 4.5): check each server
// address from the setup QR, upload every packet the server still needs, then fetch alerts, jobs
// and revocations after our cursor. Anything not signed by the command post is ignored.
import { receive } from "./mesh.js";

export const CHECK_TIMEOUT_MS = 2000;

async function fetchJson(fetchImpl, url, options = {}, timeoutMs = 8000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetchImpl(url, { ...options, signal: ctrl.signal });
    if (!res.ok) throw new Error(`${res.status} ${url}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

export class ServerLink {
  // settings: { servers: [...], sign_pk, device }; state: { cursor } (persisted by the caller)
  constructor({ store, settings, state = {}, fetchImpl = fetch, allowUnsigned = false }) {
    Object.assign(this, { store, settings, state, fetchImpl, allowUnsigned });
    this.online = false;
    this.base = null;
    this.failures = 0;
    this.lastSync = null;
    this.lastError = null;
  }

  // Online after 1 good check, offline after 2 failed ones.
  async check() {
    for (const base of this.settings.servers || []) {
      try {
        const status = await fetchJson(this.fetchImpl, `${base}/api/status`, {}, CHECK_TIMEOUT_MS);
        if (status.ok) {
          this.online = true;
          this.base = base;
          this.failures = 0;
          this.serverTime = status.time;
          return true;
        }
      } catch (e) {
        this.lastError = e.message;
      }
    }
    this.failures += 1;
    if (this.failures >= 2) this.online = false;
    return this.online;
  }

  async upload() {
    const waiting = this.store.waiting();
    let accepted = 0;
    const rejected = [];
    for (let i = 0; i < waiting.length; i += 100) {
      const chunk = waiting.slice(i, i + 100);
      const out = await fetchJson(this.fetchImpl, `${this.base}/api/packets`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ packets: chunk.map((r) => r.wire) }),
      });
      this.store.markDelivered([...out.accepted, ...out.duplicate]);
      accepted += out.accepted.length;
      // A refused packet will never be accepted (bad signature, revoked...): stop carrying it,
      // except when the phone was only sending too fast.
      const final = out.rejected.filter((r) => r.reason !== "rate_limited");
      for (const r of final) this.store.markDelivered([r.id], `refused: ${r.reason}`);
      rejected.push(...out.rejected);
    }
    return { accepted, rejected };
  }

  async pull() {
    const since = this.state.cursor || 0;
    const out = await fetchJson(this.fetchImpl,
      `${this.base}/api/outbound?since=${since}&device=${encodeURIComponent(this.settings.device || "")}`);
    const added = receive(this.store, out.packets.map((w) => ({ ...w, hops: -1 })),
      { commandPostKey: this.settings.sign_pk, allowUnsigned: this.allowUnsigned });
    this.state.cursor = out.cursor;
    return added;
  }

  // One round: check, upload, pull. Returns a summary for the status line.
  async syncOnce() {
    const online = await this.check();
    if (!online || !this.base) return { online: false };
    try {
      const up = await this.upload();
      const down = await this.pull();
      await this.store.save();
      this.lastSync = new Date();
      this.lastError = null;
      return { online: true, uploaded: up.accepted, rejected: up.rejected, received: down };
    } catch (e) {
      this.lastError = e.message;
      return { online: true, error: e.message };
    }
  }
}

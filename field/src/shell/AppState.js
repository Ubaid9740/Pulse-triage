// The phone's state: settings from setup, the device keys (secure storage), the packet store,
// the link to the command post, and the timers (sync; team pings). Screens use useApp().
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Battery from "expo-battery";
import * as Crypto from "expo-crypto";
import * as Haptics from "expo-haptics";
import * as Location from "expo-location";
import * as SecureStoreNative from "expo-secure-store";
import { Platform } from "react-native";
import bundledProfiles from "../profiles";
import { deviceIdFor, geohash, makeWire, newKeys, setRandom } from "../core/packet.js";
import { PacketStore } from "../core/store.js";
import { ServerLink } from "../core/sync.js";
import { teamPing, volunteerSetup } from "../core/payloads.js";

setRandom(Crypto.getRandomBytes);

// Secure storage for the device keys; fall back safely if keystore is unavailable in dev clients.
const SecureStore = {
  getItemAsync: async (k) => {
    try {
      if (Platform.OS !== "web" && (await SecureStoreNative.isAvailableAsync?.())) {
        const val = await SecureStoreNative.getItemAsync(k);
        if (val != null) return val;
      }
    } catch {}
    return AsyncStorage.getItem(k);
  },
  setItemAsync: async (k, v) => {
    try {
      if (Platform.OS !== "web" && (await SecureStoreNative.isAvailableAsync?.())) {
        await SecureStoreNative.setItemAsync(k, v);
      }
    } catch {}
    return AsyncStorage.setItem(k, v);
  },
  deleteItemAsync: async (k) => {
    try {
      if (Platform.OS !== "web" && (await SecureStoreNative.isAvailableAsync?.())) {
        await SecureStoreNative.deleteItemAsync(k);
      }
    } catch {}
    return AsyncStorage.removeItem(k);
  }
};

const SETTINGS = "pt.settings.v1";
const PROFILES = "pt.profiles.v1";
const KEYS = "pt.keys.v1";
export const SYNC_OFFLINE_MS = 10000;
export const SYNC_ONLINE_MS = 30000;
export const PING_JOB_MS = 2 * 60000;
export const PING_IDLE_MS = 10 * 60000;
export const TEAM_ROLES = ["volunteer", "rescue_team"];

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

export function AppProvider({ children }) {
  const store = useMemo(() => new PacketStore(AsyncStorage), []);
  const [ready, setReady] = useState(false);
  const [settings, setSettings] = useState(null);
  const [keys, setKeys] = useState(null);
  const [profiles, setProfiles] = useState(bundledProfiles);
  const [status, setStatus] = useState({ online: false, lastSync: null, error: null });
  const [, setVersion] = useState(0);
  const link = useRef(null);
  const lastPing = useRef(0);
  const syncRef = useRef(async () => {});      // the latest syncNow, for callbacks made earlier

  // Load everything saved on the phone.
  useEffect(() => {
    (async () => {
      try {
        await store.load();
        const saved = JSON.parse((await AsyncStorage.getItem(SETTINGS)) || "null");
        const savedKeys = JSON.parse((await SecureStore.getItemAsync(KEYS)) || "null");
        const savedProfiles = JSON.parse((await AsyncStorage.getItem(PROFILES)) || "null");
        if (savedProfiles) setProfiles(savedProfiles);
        if (saved && savedKeys) {
          setSettings(saved);
          setKeys(savedKeys);
        }
      } catch (err) {
        console.warn("Failed to load saved state, falling back to setup:", err);
      } finally {
        setReady(true);
      }
    })();
    return store.onChange(() => setVersion((v) => v + 1));
  }, [store]);

  const saveSettings = useCallback(async (next) => {
    setSettings(next);
    await AsyncStorage.setItem(SETTINGS, JSON.stringify(next));
  }, []);

  useEffect(() => {
    link.current = settings
      ? new ServerLink({ store, settings, state: { cursor: settings.cursor || 0 } })
      : null;
  }, [store, settings]);

  // Make, store and (if the server can be reached) send a packet from this phone.
  const send = useCallback(async (kind, payload, { urgency = 1, replaceKey = null } = {}) => {
    if (!settings || !keys) throw new Error("set up the phone first");
    const wire = makeWire(kind, payload, {
      device: settings.device, keys, boxPk: settings.box_pk, urgency, replaceKey,
      area: geohash(payload.lat ?? null, payload.lng ?? null),
    });
    store.add(wire, { mine: true });
    await store.save();
    syncRef.current().catch(() => {});
    return wire;
  }, [settings, keys, store]);

  const syncNow = useCallback(async () => {
    const l = link.current;
    if (!l) return;
    const before = new Set(store.bodies("alert").map((b) => b.id));
    const out = await l.syncOnce();
    const fresh = store.bodies("alert").filter((b) => !before.has(b.id));
    if (fresh.length) Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
    let next = settings;
    if (l.state.cursor !== settings.cursor) next = { ...next, cursor: l.state.cursor };
    if (out.online && TEAM_ROLES.includes(settings.role) && !settings.team_id) {
      try {
        const res = await fetch(`${l.base}/api/teams`);
        const team = (await res.json()).teams.find((t) => t.device_id === settings.device);
        if (team) next = { ...next, team_id: team.id };
      } catch {
        // try again next round
      }
    }
    if (next !== settings) await saveSettings(next);
    setStatus({ online: l.online, lastSync: l.lastSync, error: out.error || null, base: l.base });
  }, [store, settings, saveSettings]);
  syncRef.current = syncNow;

  const position = useCallback(async () => {
    const { status: perm } = await Location.requestForegroundPermissionsAsync();
    if (perm !== "granted") return null;
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    return { lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: Math.round(pos.coords.accuracy || 0) };
  }, []);

  // First launch: keys, device ID, the setup QR's servers and keys, and for volunteers and
  // rescue teams a "volunteer" packet so the command post adds them as a team.
  const setup = useCallback(async ({ role, name, skills = [], teamType = null, qr }) => {
    const k = newKeys();
    await SecureStore.setItemAsync(KEYS, JSON.stringify(k));
    const next = {
      role,
      name: name || (role === "helper" ? "Helper" : role),
      skills,
      capabilities: skills,
      teamType,
      device: deviceIdFor(k.publicKey),
      servers: qr?.servers || [],
      sign_pk: qr?.sign_pk || "",
      box_pk: qr?.box_pk || "",
      zones: qr?.zones || [],
      cursor: 0,
      team_id: null,
      fuel: "full",
      jobStatus: {},
    };
    setKeys(k);
    await saveSettings(next);
    for (const base of (qr?.servers || [])) {
      try {
        const res = await fetch(`${base}/api/profiles`);
        if (res.ok) {
          const p = await res.json();
          setProfiles(p);
          await AsyncStorage.setItem(PROFILES, JSON.stringify(p));
          break;
        }
      } catch {
        // offline at setup: the bundled profiles do
      }
    }
    if (TEAM_ROLES.includes(role)) {
      const where = await position().catch(() => null);
      const wire = makeWire("volunteer", volunteerSetup({ name: name || role, role, teamType, skills,
        lat: where?.lat ?? null, lng: where?.lng ?? null }), { device: next.device, keys: k, boxPk: qr?.box_pk || null, urgency: 2,
        area: geohash(where?.lat ?? null, where?.lng ?? null) });
      store.add(wire, { mine: true });
      await store.save();
    }
  }, [saveSettings, store, position]);

  const leave = useCallback(async () => {
    await AsyncStorage.removeItem(SETTINGS);
    await SecureStore.deleteItemAsync(KEYS);
    setSettings(null);
    setKeys(null);
  }, []);

  // Sync: every 10 s while offline, every 30 s while online.
  useEffect(() => {
    if (!settings) return undefined;
    let stop = false;
    let timer;
    const loop = async () => {
      await syncRef.current().catch(() => {});
      if (!stop) timer = setTimeout(loop, link.current?.online ? SYNC_ONLINE_MS : SYNC_OFFLINE_MS);
    };
    loop();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings?.device]);

  // Team phones: a location ping every 2 min on a job, every 10 min otherwise (while the app is open).
  const currentJob = useCallback(() => openJob(store, settings), [store, settings]);
  const sendPing = useCallback(async (statusOverride) => {
    if (!settings?.team_id) return false;
    const where = await position();
    if (!where) return false;
    const job = currentJob();
    const status = statusOverride || (job ? settings.jobStatus?.[job.job_id] || "assigned" : settings.teamStatus || "available");
    const battery = await Battery.getBatteryLevelAsync().catch(() => -1);
    await send("team_ping", teamPing({ teamId: settings.team_id, lat: where.lat, lng: where.lng, accuracy: where.accuracy,
      status: status === "arrived" ? "on_scene" : status, caseId: job?.case_id ?? null,
      battery: battery >= 0 ? Math.round(battery * 100) : null, fuel: settings.fuel || null }),
    { urgency: 1, replaceKey: `ping:${settings.team_id}` });
    lastPing.current = Date.now();
    return true;
  }, [settings, position, currentJob, send]);

  useEffect(() => {
    if (!settings || !TEAM_ROLES.includes(settings.role)) return undefined;
    const timer = setInterval(() => {
      const every = currentJob() ? PING_JOB_MS : PING_IDLE_MS;
      if (Date.now() - lastPing.current >= every) sendPing().catch(() => {});
    }, 15000);
    return () => clearInterval(timer);
  }, [settings, currentJob, sendPing]);

  const value = { ready, settings, keys, profiles, store, status, send, syncNow, setup, leave, saveSettings,
    position, sendPing, currentJob, counts: store.counts() };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// ---- reading the store -------------------------------------------------------------------------
// Alerts still in force: not replaced by an update, not cancelled (all-clear), not past valid_until.
export function activeAlerts(store, now = Date.now()) {
  const alerts = store.bodies("alert").map((b) => b.public);
  const replaced = new Set(alerts.map((a) => a.replaces).filter(Boolean));
  return alerts
    .filter((a) => !replaced.has(a.alert_id) && Date.parse(a.valid_until) > now)
    .sort((a, b) => Date.parse(b.issued_at) - Date.parse(a.issued_at));
}

export function jobsFor(store, settings) {
  if (!settings) return [];
  return store.bodies("job")
    .filter((b) => b.to_device === settings.device || (settings.team_id && b.public.team_id === settings.team_id))
    .map((b) => b.public)
    .sort((a, b) => b.job_id.localeCompare(a.job_id));
}

export function openJob(store, settings) {
  const done = ["done", "cant_reach"];
  return jobsFor(store, settings).find((j) => !done.includes(settings?.jobStatus?.[j.job_id])) || null;
}

export function revoked(store, settings) {
  return !!settings && store.bodies("revoke").some((b) => (b.public.device_ids || []).includes(settings.device));
}

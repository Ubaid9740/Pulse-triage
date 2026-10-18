// Wire packets, exactly as the server expects them (shared/README.md; the Python reference is
// server/app/devtools.py phone_wire). Plain JavaScript: runs in the app and in Node tests.
//
//   wire = { body: "<JSON text of the body>", sig: base64 Ed25519 signature of that text, hops }
//   body.sealed = base64 libsodium sealed box of the payload JSON, sealed to the command post
//   alerts, jobs and revocations carry body.public instead, signed by the command post
import nacl from "tweetnacl";
import util from "tweetnacl-util";
import blake from "blakejs";

const { encodeBase64, decodeBase64, decodeUTF8, encodeUTF8 } = util;

export const PUBLIC_KINDS = ["alert", "job", "revoke"];
export const PHONE_KINDS = ["report", "alert_reply", "welfare_check", "volunteer", "ack", "team_ping"];
const BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz";

// tweetnacl needs a source of random bytes on React Native (expo-crypto's getRandomBytes).
export function setRandom(getRandomBytes) {
  nacl.setPRNG((x, n) => {
    const bytes = getRandomBytes(n);
    for (let i = 0; i < n; i++) x[i] = bytes[i];
  });
}

export function newKeys() {
  const kp = nacl.sign.keyPair();
  return { publicKey: encodeBase64(kp.publicKey), secretKey: encodeBase64(kp.secretKey) };
}

// A short ID from the public key, e.g. "dev_4KQ2A9F1" (the server pins the key to it).
export function deviceIdFor(publicKey) {
  const hash = blake.blake2b(decodeBase64(publicKey), null, 5);
  return "dev_" + Array.from(hash, (b) => b.toString(16).padStart(2, "0")).join("").toUpperCase();
}

export function uuid4() {
  const b = nacl.randomBytes(16);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export function iso(date) {
  return new Date(date).toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function geohash(lat, lng, precision = 5) {
  if (lat === null || lat === undefined || lng === null || lng === undefined) return "0";
  const latR = [-90, 90];
  const lngR = [-180, 180];
  let out = "";
  let bits = 0;
  let count = 0;
  let even = true;
  while (out.length < precision) {
    const [range, value] = even ? [lngR, lng] : [latR, lat];
    const mid = (range[0] + range[1]) / 2;
    bits <<= 1;
    if (value >= mid) {
      bits |= 1;
      range[0] = mid;
    } else {
      range[1] = mid;
    }
    even = !even;
    if (++count === 5) {
      out += BASE32[bits];
      bits = 0;
      count = 0;
    }
  }
  return out;
}

export function distanceM(lat1, lng1, lat2, lng2) {
  const r = 6371000;
  const rad = Math.PI / 180;
  const dp = (lat2 - lat1) * rad;
  const dl = (lng2 - lng1) * rad;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dl / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

function concat(a, b) {
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

// libsodium crypto_box_seal: an ephemeral X25519 key, nonce = BLAKE2b-192(epk || pk).
export function seal(boxPublicKey, text) {
  const pk = decodeBase64(boxPublicKey);
  const eph = nacl.box.keyPair();
  const nonce = blake.blake2b(concat(eph.publicKey, pk), null, nacl.box.nonceLength);
  const box = nacl.box(decodeUTF8(text), nonce, pk, eph.secretKey);
  return encodeBase64(concat(eph.publicKey, box));
}

// Only the command post can open a sealed box; tests use this with a key pair they made.
export function openSealed(boxPublicKey, boxSecretKey, sealedB64) {
  const data = decodeBase64(sealedB64);
  const epk = data.slice(0, nacl.box.publicKeyLength);
  const nonce = blake.blake2b(concat(epk, decodeBase64(boxPublicKey)), null, nacl.box.nonceLength);
  const opened = nacl.box.open(data.slice(nacl.box.publicKeyLength), nonce, epk, decodeBase64(boxSecretKey));
  return opened ? encodeUTF8(opened) : null;
}

// Build a signed, sealed packet from this phone. keys: {publicKey, secretKey}; boxPk: the command
// post's box key from the setup QR (null = plain base64, only while sealing is off on the server).
export function makeWire(kind, payload, { device, keys, boxPk, urgency = 1, area = "0", replaceKey = null,
  toDevice = null, created = Date.now(), expiryHours = 24, maxHops = 12 }) {
  const json = JSON.stringify(payload);
  const body = {
    v: 1,
    id: uuid4(),
    kind,
    from_device: device,
    pubkey: keys ? keys.publicKey : "",
    created_at: iso(created),
    expires_at: iso(created + expiryHours * 3600 * 1000),
    max_hops: maxHops,
    area,
    urgency,
  };
  if (replaceKey) body.replace_key = replaceKey;
  if (toDevice) body.to_device = toDevice;
  body.sealed = boxPk ? seal(boxPk, json) : encodeBase64(decodeUTF8(json));
  const text = JSON.stringify(body);
  const sig = keys ? encodeBase64(nacl.sign.detached(decodeUTF8(text), decodeBase64(keys.secretKey))) : "";
  return { body: text, sig, hops: 0 };
}

export function parseBody(wire) {
  try {
    const body = JSON.parse(wire.body);
    return body && typeof body === "object" && body.id && body.kind ? body : null;
  } catch {
    return null;
  }
}

export function verifyWire(wire, publicKey) {
  try {
    return nacl.sign.detached.verify(decodeUTF8(wire.body), decodeBase64(wire.sig), decodeBase64(publicKey));
  } catch {
    return false;
  }
}

// Is this packet genuine? Alerts, jobs and revocations must carry the command post's signature
// (saved at setup); phone packets must match the key they carry. Unsigned ones are allowed only
// when the caller says so (development).
export function trustworthy(wire, commandPostKey, { allowUnsigned = false } = {}) {
  const body = parseBody(wire);
  if (!body) return false;
  if (PUBLIC_KINDS.includes(body.kind)) {
    return body.from_device === "command_post" && !!commandPostKey && verifyWire(wire, commandPostKey);
  }
  if (!wire.sig || !body.pubkey) return allowUnsigned;
  return verifyWire(wire, body.pubkey);
}

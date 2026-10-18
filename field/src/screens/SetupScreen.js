// 1. Setup (first launch): role, name, skills, then the command post's setup QR (or its address).
import { useState } from "react";
import { Text, TextInput, View } from "react-native";
import { useApp } from "../shell/AppState";
import QrScanner from "../shell/QrScanner";
import { Button, Chip, Err, Muted, Row, Screen, Section, s } from "../shell/ui";
import { label } from "../core/rules.js";

const ROLES = [
  ["helper", "Helper", "Residents and neighbours: get alerts, reply, report for yourself or others."],
  ["volunteer", "Volunteer", "People with a boat, a 4x4 or medical skills: also welfare checks and jobs."],
  ["rescue_team", "Rescue team", "Official teams: receive jobs, send your position, report the outcome."],
];
const SKILLS = ["boat", "4x4", "nurse_doctor", "first_aid", "swimmer", "search_rescue", "other"];   // payloads/volunteer.schema.json
const TEAM_TYPES = ["boat", "truck", "medic", "rescue", "fire", "welfare", "volunteer"];

const DEFAULT_SERVERS = [
  "http://192.168.100.72:8000",
  "http://10.0.2.2:8000",
  "http://127.0.0.1:8000",
  "http://localhost:8000",
];

const DEFAULT_FALLBACK_QR = {
  v: 1,
  servers: DEFAULT_SERVERS,
  sign_pk: "",
  box_pk: "",
  zones: [],
};

function checkQr(doc) {
  if (!doc || doc.v !== 1 || !Array.isArray(doc.servers) || !doc.sign_pk || !doc.box_pk) {
    throw new Error("That is not a valid PulseTriage setup code (missing sign_pk or box_pk).");
  }
  return doc;
}

export default function SetupScreen() {
  const { setup } = useApp();
  const [role, setRole] = useState("helper");
  const [name, setName] = useState("");
  const [skills, setSkills] = useState([]);
  const [teamType, setTeamType] = useState("volunteer");
  const [scanning, setScanning] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [address, setAddress] = useState("http://192.168.");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function finish(qr) {
    setBusy(true);
    setError(null);
    try {
      await setup({
        role,
        name: name.trim(),
        skills: role === "helper" ? [] : skills,
        teamType: role === "helper" ? null : teamType,
        qr: checkQr(qr),
      });
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  async function finishHelper() {
    setBusy(true);
    setError(null);
    let chosenQr = DEFAULT_FALLBACK_QR;
    for (const srv of DEFAULT_SERVERS) {
      try {
        const controller = new AbortController();
        const tid = setTimeout(() => controller.abort(), 600);
        const res = await fetch(`${srv}/api/setup-qr`, { signal: controller.signal });
        clearTimeout(tid);
        if (res.ok) {
          const live = await res.json();
          if (live && live.v === 1) {
            chosenQr = { ...live, servers: [srv, ...(live.servers || []).filter((x) => x !== srv)] };
            break;
          }
        }
      } catch {
        // Continue to fallback
      }
    }
    try {
      await setup({
        role: "helper",
        name: name.trim(),
        skills: [],
        teamType: null,
        qr: chosenQr,
      });
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  async function fromAddress() {
    try {
      setBusy(true);
      setError(null);
      const base = address.trim().replace(/\/+$/, "");
      const res = await fetch(`${base}/api/setup-qr`);
      const qr = await res.json();
      await finish({ ...qr, servers: [base, ...qr.servers.filter((x) => x !== base)] });
    } catch (e) {
      setError(`Could not reach ${address}: ${e.message}`);
      setBusy(false);
    }
  }

  return (
    <Screen title="PulseTriage: set up this phone">
      <Section title="Who are you?">
        {ROLES.map(([id, title, text]) => (
          <View key={id} style={{ gap: 4 }}>
            <Chip label={title} on={role === id} onPress={() => { setRole(id); setError(null); }} />
            <Muted>{text}</Muted>
          </View>
        ))}
      </Section>

      <Section title="Name (optional)">
        <TextInput
          style={s.input}
          value={name}
          onChangeText={setName}
          placeholder={role === "helper" ? "Your first name" : "e.g. Boat 7"}
          maxLength={60}
        />
      </Section>

      {role === "helper" ? (
        <Section title="Quick Start">
          <Muted>
            Helpers can start reporting emergencies immediately without scanning. Default fallback command post connection is enabled.
          </Muted>
          <Button
            title={busy ? "Starting…" : "Start as Helper"}
            kind="primary"
            big
            onPress={finishHelper}
            disabled={busy}
          />

          <View style={{ marginTop: 12 }}>
            <Button
              title={showAdvanced ? "Hide QR / Address Setup" : "Optional: Scan Command Post QR"}
              kind="plain"
              onPress={() => setShowAdvanced(!showAdvanced)}
            />
          </View>

          {showAdvanced && (
            <View style={{ marginTop: 8, gap: 8 }}>
              {scanning ? (
                <QrScanner
                  onCode={(text) => {
                    try {
                      setScanning(false);
                      finish(JSON.parse(text));
                    } catch {
                      setError("That is not a PulseTriage setup code.");
                    }
                  }}
                />
              ) : (
                <Button title="Scan Setup QR" kind="dark" onPress={() => setScanning(true)} disabled={busy} />
              )}
              <Text style={{ fontWeight: "700", marginTop: 4 }}>Or type Command Post address</Text>
              <TextInput
                style={s.input}
                value={address}
                onChangeText={setAddress}
                autoCapitalize="none"
                keyboardType="url"
                placeholder="http://192.168.1.20:8000"
              />
              <Button title={busy ? "Connecting…" : "Connect"} onPress={fromAddress} disabled={busy} />
            </View>
          )}
          <Err>{error}</Err>
        </Section>
      ) : (
        <>
          <Section title="Capabilities & Skills">
            <Muted>Select any resources or skills your team has available:</Muted>
            <Row>
              {SKILLS.map((k) => (
                <Chip
                  key={k}
                  label={label(k)}
                  on={skills.includes(k)}
                  onPress={() => setSkills((old) => (old.includes(k) ? old.filter((x) => x !== k) : [...old, k]))}
                />
              ))}
            </Row>
          </Section>

          <Section title="Team type">
            <Row>
              {TEAM_TYPES.map((t) => (
                <Chip key={t} label={label(t)} on={teamType === t} onPress={() => setTeamType(t)} />
              ))}
            </Row>
          </Section>

          <Section title="Command Post Verification Required">
            <View style={{ backgroundColor: "#eff6ff", borderColor: "#93c5fd", borderWidth: 1, borderRadius: 8, padding: 12, gap: 4, marginBottom: 8 }}>
              <Text style={{ fontWeight: "800", color: "#1d4ed8" }}>Command Post QR Scan Required</Text>
              <Muted>
                {role === "rescue_team" ? "Rescue teams" : "Volunteers"} must scan the Command Post setup QR code to authenticate their device, receive authentic alert signing keys (sign_pk), and box keys (box_pk) to unlock team jobs and outreach.
              </Muted>
            </View>

            {scanning ? (
              <QrScanner
                onCode={(text) => {
                  try {
                    setScanning(false);
                    finish(JSON.parse(text));
                  } catch {
                    setError("That is not a PulseTriage setup code.");
                  }
                }}
              />
            ) : (
              <Button title="Scan the setup QR" kind="primary" big onPress={() => setScanning(true)} disabled={busy} />
            )}

            <Text style={{ fontWeight: "700", marginTop: 10 }}>Or enter Command Post address</Text>
            <TextInput
              style={s.input}
              value={address}
              onChangeText={setAddress}
              autoCapitalize="none"
              keyboardType="url"
              placeholder="http://192.168.1.20:8000"
            />
            <Button title={busy ? "Verifying…" : "Connect & Verify"} kind="dark" onPress={fromAddress} disabled={busy} />
            <Err>{error}</Err>
          </Section>
        </>
      )}
    </Screen>
  );
}

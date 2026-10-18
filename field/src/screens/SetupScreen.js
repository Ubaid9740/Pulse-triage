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

function checkQr(doc) {
  if (!doc || doc.v !== 1 || !Array.isArray(doc.servers) || !doc.sign_pk || !doc.box_pk) {
    throw new Error("That is not a PulseTriage setup code.");
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
  const [address, setAddress] = useState("http://192.168.");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function finish(qr) {
    setBusy(true);
    setError(null);
    try {
      await setup({ role, name: name.trim(), skills, teamType: role === "helper" ? null : teamType, qr: checkQr(qr) });
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  async function fromAddress() {
    try {
      const base = address.trim().replace(/\/+$/, "");
      const res = await fetch(`${base}/api/setup-qr`);
      const qr = await res.json();
      await finish({ ...qr, servers: [base, ...qr.servers.filter((x) => x !== base)] });
    } catch (e) {
      setError(`Could not reach ${address}: ${e.message}`);
    }
  }

  return (
    <Screen title="PulseTriage: set up this phone">
      <Section title="Who are you?">
        {ROLES.map(([id, title, text]) => (
          <View key={id} style={{ gap: 4 }}>
            <Chip label={title} on={role === id} onPress={() => setRole(id)} />
            <Muted>{text}</Muted>
          </View>
        ))}
      </Section>
      <Section title="Name (optional)">
        <TextInput style={s.input} value={name} onChangeText={setName} placeholder={role === "helper" ? "Your first name" : "e.g. Boat 7"} maxLength={60} />
      </Section>
      {role !== "helper" && (
        <>
          <Section title="Skills">
            <Row>{SKILLS.map((k) => <Chip key={k} label={label(k)} on={skills.includes(k)}
              onPress={() => setSkills((old) => (old.includes(k) ? old.filter((x) => x !== k) : [...old, k]))} />)}</Row>
          </Section>
          <Section title="Team type">
            <Row>{TEAM_TYPES.map((t) => <Chip key={t} label={label(t)} on={teamType === t} onPress={() => setTeamType(t)} />)}</Row>
          </Section>
        </>
      )}
      <Section title="Connect to the command post">
        <Muted>Scan the setup code on the dashboard (Phone setup). It saves the server address and the key that proves alerts are real.</Muted>
        {scanning ? (
          <QrScanner onCode={(text) => {
            try {
              setScanning(false);
              finish(JSON.parse(text));
            } catch {
              setError("That is not a PulseTriage setup code.");
            }
          }} />
        ) : (
          <Button title="Scan the setup QR" kind="dark" big onPress={() => setScanning(true)} disabled={busy} />
        )}
        <Text style={{ fontWeight: "700", marginTop: 6 }}>Or type the laptop's address</Text>
        <TextInput style={s.input} value={address} onChangeText={setAddress} autoCapitalize="none" keyboardType="url"
          placeholder="http://192.168.1.20:8000" />
        <Button title={busy ? "Setting up…" : "Connect"} onPress={fromAddress} disabled={busy} />
        <Err>{error}</Err>
      </Section>
    </Screen>
  );
}

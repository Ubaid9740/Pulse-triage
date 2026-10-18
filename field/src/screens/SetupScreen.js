// 1. Setup (first launch): role, name, skills, then the command post's setup QR (or its address).
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useApp } from "../shell/AppState";
import QrScanner from "../shell/QrScanner";
import { Button, Chip, Err, Field, Input, Notice, Row, Screen, Section, T } from "../shell/ui";
import Icon from "../shell/Icon";
import { label } from "../core/rules.js";

const ROLES = [
["helper", "Helper", "Residents and neighbours: get alerts, reply, report for yourself or others."],
["volunteer", "Volunteer", "People with a boat, a 4x4 or medical skills: also welfare checks and jobs."],
["rescue_team", "Rescue team", "Official teams: receive jobs, send your position, report the outcome."]];

const ROLE_ICON = { helper: "user", volunteer: "userCheck", rescue_team: "users" };
const SKILLS = ["boat", "4x4", "nurse_doctor", "first_aid", "swimmer", "search_rescue", "other"]; // payloads/volunteer.schema.json
const TEAM_TYPES = ["boat", "truck", "medic", "rescue", "fire", "welfare", "volunteer"];

const DEFAULT_SERVERS = [
"http://192.168.100.72:8000",
"http://10.0.2.2:8000",
"http://127.0.0.1:8000",
"http://localhost:8000"];


const DEFAULT_FALLBACK_QR = {
  v: 1,
  servers: DEFAULT_SERVERS,
  sign_pk: "",
  box_pk: "",
  zones: []
};

function checkQr(doc) {
  if (!doc || doc.v !== 1 || !Array.isArray(doc.servers) || !doc.sign_pk || !doc.box_pk) {
    throw new Error("That is not a valid Pulse setup code (missing sign_pk or box_pk).");
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
        qr: checkQr(qr)
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
      }}
    try {
      await setup({
        role: "helper",
        name: name.trim(),
        skills: [],
        teamType: null,
        qr: chosenQr
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

  const onCode = (text) => {
    try {
      setScanning(false);
      finish(JSON.parse(text));
    } catch {
      setError("That is not a Pulse setup code.");
    }
  };

  const addressForm = (buttonTitle, kind) =>
  <View style={styles.addressBox}>
      <Field label="Or type the command post address" hint="Shown under the QR on the command post laptop">
        <Input value={address} onChangeText={setAddress} autoCapitalize="none" autoCorrect={false} keyboardType="url"
      placeholder="http://192.168.1.20:8000" returnKeyType="go" onSubmitEditing={() => !busy && fromAddress()} />
      </Field>
      <Button title={busy ? kind === "dark" ? "Verifying…" : "Connecting…" : buttonTitle} icon="link" kind={kind} busy={busy} onPress={fromAddress} />
    </View>;


  return (
    <Screen title="Pulse: set up this phone" subtitle="Takes under a minute">
      <Section title="Who are you?" hint="This decides what the app shows you.">
        <View style={styles.roles} accessibilityRole="radiogroup">
          {ROLES.map(([id, title, text]) => {
            const on = role === id;
            return (
              <Pressable key={id} onPress={() => {setRole(id);setError(null);}} accessibilityRole="radio" accessibilityState={{ selected: on }}
              style={({ pressed }) => [styles.role, on && styles.roleOn, pressed && { opacity: 0.85 }]}>
                <View style={[styles.roleIcon, on && styles.roleIconOn]}>
                  <Icon name={ROLE_ICON[id]} size={22} color={on ? "#fff" : T.ink2} />
                </View>
                <View style={styles.roleText}>
                  <Text style={[styles.roleTitle, on && { color: T.primary }]}>{title}</Text>
                  <Text style={styles.roleDesc}>{text}</Text>
                </View>
                <View style={[styles.radio, on && styles.radioOn]}>{on ? <View style={styles.radioDot} /> : null}</View>
              </Pressable>);

          })}
        </View>
      </Section>

      <Section>
        <Field label="Name" optional>
          <Input value={name} onChangeText={setName} placeholder={role === "helper" ? "Your first name" : "e.g. Boat 7"} maxLength={60}
          autoCapitalize="words" />
        </Field>
      </Section>

      {role === "helper" ?
      <Section title="Quick start">
          <Text style={styles.body}>
            Helpers can start reporting emergencies immediately without scanning. Default fallback command post connection is enabled.
          </Text>
          <Button title={busy ? "Starting…" : "Start as Helper"} kind="primary" big icon="check" onPress={finishHelper} busy={busy} />

          <Pressable onPress={() => setShowAdvanced(!showAdvanced)} accessibilityRole="button" accessibilityState={{ expanded: showAdvanced }}
        style={({ pressed }) => [styles.disclosure, pressed && { opacity: 0.7 }]}>
            <Icon name="qr" size={20} color={T.primary} />
            <Text style={styles.disclosureText}>{showAdvanced ? "Hide QR / Address Setup" : "Optional: Scan Command Post QR"}</Text>
            <View style={{ transform: [{ rotate: showAdvanced ? "90deg" : "0deg" }] }}>
              <Icon name="chevronRight" size={20} color={T.primary} />
            </View>
          </Pressable>

          {showAdvanced &&
        <View style={styles.advanced}>
              {scanning ?
          <>
                  <QrScanner onCode={onCode} />
                  <Button title="Stop scanning" icon="x" onPress={() => setScanning(false)} />
                </> :

          <Button title="Scan Setup QR" icon="scan" kind="dark" onPress={() => setScanning(true)} disabled={busy} />
          }
              {addressForm("Connect", "plain")}
            </View>
        }
          <Err>{error}</Err>
        </Section> :

      <>
          <Section title="Capabilities and skills" hint="Select any resources or skills your team has available.">
            <Row>
              {SKILLS.map((k) =>
            <Chip key={k} label={label(k)} on={skills.includes(k)}
            onPress={() => setSkills((old) => old.includes(k) ? old.filter((x) => x !== k) : [...old, k])} />
            )}
            </Row>
          </Section>

          <Section title="Team type">
            <Row>
              {TEAM_TYPES.map((t) =>
            <Chip single key={t} label={label(t)} on={teamType === t} onPress={() => setTeamType(t)} />
            )}
            </Row>
          </Section>

          <Section title="Connect to the command post">
            <Notice tone="info" icon="shield" title="Command post QR scan required">
              {`${role === "rescue_team" ? "Rescue teams" : "Volunteers"} must scan the Command Post setup QR code to authenticate their device, receive authentic alert signing keys (sign_pk), and box keys (box_pk) to unlock team jobs and outreach.`}
            </Notice>
            {scanning ?
          <>
                <QrScanner onCode={onCode} />
                <Button title="Stop scanning" icon="x" onPress={() => setScanning(false)} />
              </> :

          <Button title="Scan the setup QR" icon="scan" kind="primary" big onPress={() => setScanning(true)} disabled={busy} />
          }
            {addressForm("Connect & Verify", "dark")}
            <Err>{error}</Err>
          </Section>
        </>
      }
    </Screen>);

}

const styles = StyleSheet.create({
  roles: { gap: 10 },
  role: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 12, borderWidth: 1.5, borderColor: T.lineStrong,
    backgroundColor: T.panel, minHeight: 72 },
  roleOn: { borderColor: T.primary, backgroundColor: T.primarySoft },
  roleIcon: { width: 44, height: 44, borderRadius: 10, backgroundColor: T.panel3, alignItems: "center", justifyContent: "center" },
  roleIconOn: { backgroundColor: T.primary },
  roleText: { flex: 1, gap: 2 },
  roleTitle: { fontSize: 17, fontWeight: "800", color: T.ink },
  roleDesc: { fontSize: 14, color: T.muted, lineHeight: 19 },
  radio: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: T.lineStrong, alignItems: "center", justifyContent: "center" },
  radioOn: { borderColor: T.primary },
  radioDot: { width: 12, height: 12, borderRadius: 6, backgroundColor: T.primary },
  body: { fontSize: 15, color: T.ink2, lineHeight: 21 },
  disclosure: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 48, paddingTop: 4 },
  disclosureText: { flex: 1, fontSize: 16, fontWeight: "700", color: T.primary },
  advanced: { gap: 10 },
  addressBox: { gap: 10, paddingTop: 12, borderTopWidth: 1, borderTopColor: T.line }
});

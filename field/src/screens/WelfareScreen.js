// 5. Welfare check: "I checked on someone": who or where, then Safe, Needs help or Not found.
import { useState } from "react";
import { Text, TextInput } from "react-native";
import { useApp } from "../shell/AppState";
import { Button, C, Chip, Err, Muted, Row, Screen, Section, s } from "../shell/ui";
import { welfareCheck } from "../core/payloads.js";

export default function WelfareScreen({ back, go }) {
  const { settings, send, position } = useApp();
  const [registryId, setRegistryId] = useState("");
  const [landmark, setLandmark] = useState("");
  const [note, setNote] = useState("");
  const [result, setResult] = useState("safe");
  const [done, setDone] = useState(false);
  const [error, setError] = useState(null);

  if (!settings?.sign_pk || !settings?.box_pk) {
    return (
      <Screen title="Welfare check" onBack={back}>
        <Section title="Verification Required">
          <Text style={{ color: C.orange, fontWeight: "700" }}>Command Post QR Scan Required</Text>
          <Muted>You must scan the Command Post setup QR code to receive authentic signing and encryption keys before unlocking welfare checks.</Muted>
          <Button title="Back to home" onPress={back} />
        </Section>
      </Screen>
    );
  }

  async function submit() {
    setError(null);
    try {
      const where = await position().catch(() => null);
      await send("welfare_check", welfareCheck({ result, registryId: registryId.trim() || null, landmark: landmark.trim(),
        note: note.trim(), lat: where?.lat ?? null, lng: where?.lng ?? null }), { urgency: result === "needs_help" ? 3 : 1 });
      setDone(true);
    } catch (e) {
      setError(e.message);
    }
  }

  if (done) {
    return (
      <Screen title="Welfare check" onBack={back}>
        <Text style={{ fontSize: 20, fontWeight: "800", color: C.green }}>Saved. Thank you.</Text>
        {result === "needs_help" && <Button big kind="primary" title="Describe what they need" onPress={() => go("report", { forWhom: "neighbour" })} />}
        <Button title="Check on someone else" onPress={() => { setDone(false); setRegistryId(""); setLandmark(""); setNote(""); }} />
        <Button title="Back to home" kind="dark" onPress={back} />
      </Screen>
    );
  }
  return (
    <Screen title="I checked on someone" onBack={back}>
      <Section title="Who or where">
        <TextInput style={s.input} value={registryId} onChangeText={setRegistryId} autoCapitalize="characters" placeholder="Registry ID, e.g. R-0007 (if you have it)" />
        <TextInput style={s.input} value={landmark} onChangeText={setLandmark} placeholder="House or landmark" />
      </Section>
      <Section title="How are they?">
        <Row>{[["safe", "Safe"], ["needs_help", "Needs help"], ["not_found", "Not found"]].map(([v, t]) =>
          <Chip key={v} label={t} on={result === v} onPress={() => setResult(v)} />)}</Row>
        <TextInput style={[s.input, { minHeight: 70 }]} multiline value={note} onChangeText={setNote} placeholder="Note (optional)" />
      </Section>
      <Muted>Your position is added if GPS is on.</Muted>
      <Err>{error}</Err>
      <Button big kind="dark" title="Send" onPress={submit} />
    </Screen>
  );
}

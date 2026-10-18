// 5. Welfare check: "I checked on someone": who or where, then Safe, Needs help or Not found.
import { useEffect, useState } from "react";
import { Alert as Confirm, Pressable, StyleSheet, Text, View } from "react-native";
import { useApp } from "../shell/AppState";
import { Button, Err, Field, Input, Muted, Notice, Screen, Section, T, TONES } from "../shell/ui";
import Icon from "../shell/Icon";
import { welfareCheck } from "../core/payloads.js";

const RESULTS = [
["safe", "Safe", "check", "success"],
["needs_help", "Needs help", "lifebuoy", "critical"],
["not_found", "Not found", "search", "warning"]];

export default function WelfareScreen({ back, go, setLeaveGuard }) {
  const { settings, send, position, status } = useApp();
  const [registryId, setRegistryId] = useState("");
  const [landmark, setLandmark] = useState("");
  const [note, setNote] = useState("");
  const [result, setResult] = useState("safe");
  const [done, setDone] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const verified = Boolean(settings?.sign_pk && settings?.box_pk);

  // Ask before Back throws away what was typed.
  const dirty = verified && !done && Boolean(registryId.trim() || landmark.trim() || note.trim());
  useEffect(() => {
    if (!setLeaveGuard) return undefined;
    setLeaveGuard(dirty ? (pop) => {
      Confirm.alert("Discard this check?", "What you entered has not been sent yet.",
      [{ text: "Keep editing", style: "cancel" }, { text: "Discard", style: "destructive", onPress: pop }]);
      return true;
    } : null);
    return () => setLeaveGuard(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty]);

  if (!verified) {
    return (
      <Screen title="Welfare check" onBack={back}>
        <Notice tone="warning" icon="lock" title="Command post QR scan required"
        action={<Button title="Back to home" icon="home" onPress={back} />}>
          You must scan the Command Post setup QR code to receive authentic signing and encryption keys before unlocking welfare checks.
        </Notice>
      </Screen>);
  }

  async function submit() {
    if (sending) return;
    setError(null);
    setSending(true);
    try {
      const where = await position().catch(() => null);
      await send("welfare_check", welfareCheck({ result, registryId: registryId.trim() || null, landmark: landmark.trim(),
        note: note.trim(), lat: where?.lat ?? null, lng: where?.lng ?? null }), { urgency: result === "needs_help" ? 3 : 1 });
      setDone(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  }

  if (done) {
    return (
      <Screen title="Welfare check" onBack={back}>
        <Notice tone="success" icon="check" title="Saved. Thank you.">
          {status.online ? "This phone is connected: it is on its way to the command post." : "It is sent as soon as this phone has a connection."}
        </Notice>
        {result === "needs_help" && <Button big kind="primary" icon="lifebuoy" title="Describe what they need" onPress={() => go("report", { forWhom: "neighbour" })} />}
        <Button title="Check on someone else" icon="userCheck" onPress={() => {setDone(false);setRegistryId("");setLandmark("");setNote("");}} />
        <Button title="Back to home" icon="home" kind="dark" onPress={back} />
      </Screen>);
  }
  return (
    <Screen title="I checked on someone" subtitle="Welfare check" onBack={back}
    footer={
    <>
          <Err>{error}</Err>
          <Button big kind="dark" icon="send" title={sending ? "Saving…" : "Send"} busy={sending} onPress={submit} />
        </>
    }>
      <Section title="How are they?">
        <View style={styles.results} accessibilityRole="radiogroup">
          {RESULTS.map(([v, t, icon, tone]) => {
            const on = result === v;
            const [fg, bg, border] = TONES[tone];
            return (
              <Pressable key={v} onPress={() => setResult(v)} accessibilityRole="radio" accessibilityState={{ selected: on }}
              style={({ pressed }) => [styles.result, on && { backgroundColor: bg, borderColor: fg }, pressed && { opacity: 0.8 }]}>
                <Icon name={icon} size={26} color={on ? fg : T.muted} strokeWidth={2.4} />
                <Text style={[styles.resultText, on && { color: fg }]}>{t}</Text>
                {on ? <View style={[styles.tick, { borderColor: border }]}><Icon name="check" size={12} color={fg} strokeWidth={3} /></View> : null}
              </Pressable>);
          })}
        </View>
      </Section>
      <Section title="Who or where" hint="Give the registry ID if you have it, otherwise the house or a landmark.">
        <Field label="Registry ID" optional>
          <Input value={registryId} onChangeText={setRegistryId} autoCapitalize="characters" autoCorrect={false} placeholder="e.g. R-0007" />
        </Field>
        <Field label="House or landmark">
          <Input value={landmark} onChangeText={setLandmark} placeholder="e.g. Blue gate, lane 3" />
        </Field>
        <Field label="Note" optional>
          <Input multiline value={note} onChangeText={setNote} placeholder="What you saw" />
        </Field>
      </Section>
      <Muted>Your position is added if GPS is on.</Muted>
    </Screen>);
}

const styles = StyleSheet.create({
  results: { flexDirection: "row", gap: 8 },
  result: { flex: 1, minHeight: 92, borderRadius: 12, borderWidth: 1.5, borderColor: T.lineStrong, backgroundColor: T.panel,
    alignItems: "center", justifyContent: "center", gap: 8, paddingHorizontal: 6 },
  resultText: { fontSize: 15, fontWeight: "800", color: T.ink2, textAlign: "center" },
  tick: { position: "absolute", top: 6, right: 6, width: 20, height: 20, borderRadius: 10, borderWidth: 1, backgroundColor: "#fff",
    alignItems: "center", justifyContent: "center" }
});

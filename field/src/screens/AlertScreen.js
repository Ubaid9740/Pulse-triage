// 3. Alert: full screen, read aloud, three steps, the place to go, three reply buttons, pass it on.
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import * as Speech from "expo-speech";
import { activeAlerts, useApp } from "../shell/AppState";
import { BAND, Button, C, Muted, Screen, Section } from "../shell/ui";
import { label } from "../core/rules.js";
import { alertReply } from "../core/payloads.js";

export default function AlertScreen({ params, back, go }) {
  const { store, profiles, send, position } = useApp();
  const alert = activeAlerts(store).find((a) => a.alert_id === params.id) || activeAlerts(store)[0];
  const [replied, setReplied] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => () => Speech.stop(), []);
  if (!alert) return <Screen title="Alert" onBack={back}><Muted>This alert is no longer active.</Muted></Screen>;

  const steps = alert.do_now?.en || [];
  const text = [alert.headline?.en, ...steps, ...(alert.places || []).map((p) => `Go to ${p.name}.`)].filter(Boolean).join(". ");
  const tips = profiles?.profiles?.[alert.hazard]?.tips?.en || [];

  async function reply(status) {
    setError(null);
    try {
      const where = await position().catch(() => null);
      await send("alert_reply", alertReply({ alertId: alert.alert_id, status, lat: where?.lat ?? null, lng: where?.lng ?? null }),
        { urgency: status === "need_help" ? 3 : 1 });
      setReplied(status);
      if (status === "need_help") go("report", { hazard: alert.hazard, alertId: alert.alert_id, forWhom: "self" });
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <Screen title="Alert" onBack={back}>
      <View style={{ borderRadius: 14, overflow: "hidden" }}>
        <Text style={{ backgroundColor: alert.cancel ? C.green : BAND[alert.severity], padding: 16, fontSize: 22, fontWeight: "900" }}>
          {alert.cancel ? "ALL CLEAR" : `${label(alert.hazard)} ${alert.severity}`.toUpperCase()}
        </Text>
        <View style={{ backgroundColor: "#fff", padding: 16, gap: 10 }}>
          <Text style={{ fontSize: 22, fontWeight: "800" }}>{alert.headline?.en}</Text>
          {steps.map((step, i) => <Text key={i} style={{ fontSize: 18 }}>{i + 1}. {step}</Text>)}
          {(alert.places || []).map((p) => (
            <View key={p.id} style={{ backgroundColor: "#eef7f1", borderRadius: 10, padding: 10 }}>
              <Muted>GO TO</Muted>
              <Text style={{ fontSize: 17, fontWeight: "700" }}>{p.name}{p.space_left != null ? ` · space for ${p.space_left}` : ""}</Text>
            </View>
          ))}
          <Muted>{alert.zones.join(", ")} · until {new Date(alert.valid_until).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · signed by the command post</Muted>
        </View>
      </View>
      <Button title="Read aloud" kind="dark" onPress={() => Speech.speak(text, { language: "en" })} />
      {!alert.cancel && (
        <>
          <Button big kind="green" title={replied === "safe" ? "Sent: I'm safe" : "I'm safe"} onPress={() => reply("safe")} />
          <Button big kind="primary" title="I need help" onPress={() => reply("need_help")} />
          <Button big title={replied === "helping" ? "Sent: I'm helping others" : "I'm helping others"} onPress={() => reply("helping")} />
        </>
      )}
      {error ? <Text style={{ color: C.red }}>{error}</Text> : null}
      <Section title="Pass it on">
        <Text style={{ fontSize: 16 }}>Check on neighbours who are elderly, ill, alone or have small children.</Text>
      </Section>
      {tips.length > 0 && (
        <Section title="Safety tips">{tips.map((t, i) => <Text key={i}>• {t}</Text>)}</Section>
      )}
    </Screen>
  );
}

// 3. Alert: full screen, read aloud, three steps, the place to go, three reply buttons, pass it on.
import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import * as Speech from "expo-speech";
import { activeAlerts, useApp } from "../shell/AppState";
import { BAND, BAND_INK, Button, Err, Muted, Notice, Pill, Screen, Section, T } from "../shell/ui";
import Icon from "../shell/Icon";
import { label } from "../core/rules.js";
import { alertReply } from "../core/payloads.js";

const REPLY_TEXT = { safe: "I'm safe", need_help: "I need help", helping: "I'm helping others" };

export default function AlertScreen({ params, back, go }) {
  const { store, profiles, send, position, status } = useApp();
  const alert = activeAlerts(store).find((a) => a.alert_id === params.id) || activeAlerts(store)[0];
  const [replied, setReplied] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => () => Speech.stop(), []);
  if (!alert) {
    return (
      <Screen title="Alert" onBack={back}>
        <Notice tone="info" icon="bell" title="No longer active">This alert is no longer active.</Notice>
        <Button title="Back to home" icon="home" onPress={back} />
      </Screen>);
  }

  const steps = alert.do_now?.en || [];
  const text = [alert.headline?.en, ...steps, ...(alert.places || []).map((p) => `Go to ${p.name}.`)].filter(Boolean).join(". ");
  const tips = profiles?.profiles?.[alert.hazard]?.tips?.en || [];
  const bandColour = alert.cancel ? T.green : BAND[alert.severity];
  const bandInk = alert.cancel ? "#fff" : BAND_INK[alert.severity];

  async function reply(replyStatus) {
    if (busy) return;
    setError(null);
    setBusy(replyStatus);
    try {
      const where = await position().catch(() => null);
      await send("alert_reply", alertReply({ alertId: alert.alert_id, status: replyStatus, lat: where?.lat ?? null, lng: where?.lng ?? null }),
      { urgency: replyStatus === "need_help" ? 3 : 1 });
      setReplied(replyStatus);
      if (replyStatus === "need_help") go("report", { hazard: alert.hazard, alertId: alert.alert_id, forWhom: "self" });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Screen title="Alert" subtitle={`${alert.zones.length} zone${alert.zones.length === 1 ? "" : "s"}`} onBack={back}>
      <View style={styles.card}>
        <View style={[styles.band, { backgroundColor: bandColour }]}>
          <Icon name={alert.cancel ? "check" : "alert"} size={26} color={bandInk} strokeWidth={2.4} />
          <Text style={[styles.bandText, { color: bandInk }]}>
            {alert.cancel ? "ALL CLEAR" : `${label(alert.hazard)} ${alert.severity}`.toUpperCase()}
          </Text>
        </View>
        <View style={styles.body}>
          <Text style={styles.headline}>{alert.headline?.en}</Text>
          {steps.length > 0 &&
          <View style={styles.steps}>
              {steps.map((step, i) =>
            <View key={i} style={styles.step}>
                  <View style={styles.stepNum}><Text style={styles.stepNumText}>{i + 1}</Text></View>
                  <Text style={styles.stepText}>{step}</Text>
                </View>
            )}
            </View>
          }
          {(alert.places || []).map((p) =>
          <View key={p.id} style={styles.place}>
              <Icon name="home" size={22} color={T.green} />
              <View style={{ flex: 1 }}>
                <Text style={styles.placeLabel}>GO TO</Text>
                <Text style={styles.placeName}>{p.name}{p.space_left != null ? ` · space for ${p.space_left}` : ""}</Text>
              </View>
            </View>
          )}
          <View style={styles.meta}>
            <View style={styles.metaItem}><Icon name="mapPin" size={15} color={T.muted} /><Text style={styles.metaText}>{alert.zones.join(", ")}</Text></View>
            <View style={styles.metaItem}><Icon name="shield" size={15} color={T.green} /><Text style={[styles.metaText, { color: T.green }]}>signed by the command post</Text></View>
          </View>
        </View>
      </View>

      <Button title="Read aloud" icon="volume" kind="dark" onPress={() => Speech.speak(text, { language: "en" })} />

      {!alert.cancel &&
      <Section title="Reply to the command post" hint="Your position is added if GPS is on.">
          {replied ?
        <Pill tone="success" icon="check"
        label={`Reply saved: ${REPLY_TEXT[replied]}${status.online ? "" : " · sends when connected"}`} /> :
        null}
          <Button big kind="green" icon="check" busy={busy === "safe"} disabled={!!busy && busy !== "safe"}
        title={replied === "safe" ? "Saved: I'm safe" : "I'm safe"} onPress={() => reply("safe")} />
          <Button big kind="primary" icon="lifebuoy" busy={busy === "need_help"} disabled={!!busy && busy !== "need_help"}
        title="I need help" onPress={() => reply("need_help")} />
          <Button big icon="users" busy={busy === "helping"} disabled={!!busy && busy !== "helping"}
        title={replied === "helping" ? "Saved: I'm helping others" : "I'm helping others"} onPress={() => reply("helping")} />
        </Section>
      }
      <Err>{error}</Err>
      <Section title="Pass it on">
        <Text style={styles.pass}>Check on neighbours who are elderly, ill, alone or have small children.</Text>
      </Section>
      {tips.length > 0 &&
      <Section title="Safety tips">
          {tips.map((t, i) =>
        <View key={i} style={styles.tip}><View style={styles.dot} /><Text style={styles.tipText}>{t}</Text></View>
        )}
        </Section>
      }
      {!tips.length && alert.cancel ? <Muted>Keep the app open: the command post may send updates.</Muted> : null}
    </Screen>);
}

const styles = StyleSheet.create({
  card: { borderRadius: 14, overflow: "hidden", borderWidth: 1, borderColor: T.line, backgroundColor: T.panel },
  band: { flexDirection: "row", alignItems: "center", gap: 10, padding: 16 },
  bandText: { fontSize: 22, fontWeight: "900", letterSpacing: 0.5, flex: 1 },
  body: { padding: 16, gap: 14 },
  headline: { fontSize: 23, fontWeight: "800", color: T.ink, lineHeight: 30 },
  steps: { gap: 12 },
  step: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  stepNum: { width: 30, height: 30, borderRadius: 15, backgroundColor: T.ink, alignItems: "center", justifyContent: "center", marginTop: 1 },
  stepNumText: { color: "#fff", fontWeight: "800", fontSize: 15 },
  stepText: { flex: 1, fontSize: 18, color: T.ink, lineHeight: 25 },
  place: { flexDirection: "row", gap: 12, alignItems: "center", backgroundColor: T.greenSoft, borderRadius: 12, padding: 12,
    borderWidth: 1, borderColor: T.greenLine },
  placeLabel: { fontSize: 12, fontWeight: "900", color: T.green, letterSpacing: 0.8 },
  placeName: { fontSize: 17, fontWeight: "800", color: T.ink },
  meta: { gap: 6, paddingTop: 12, borderTopWidth: 1, borderTopColor: T.line },
  metaItem: { flexDirection: "row", alignItems: "center", gap: 8 },
  metaText: { fontSize: 14, color: T.muted, flex: 1 },
  pass: { fontSize: 16, color: T.ink2, lineHeight: 22 },
  tip: { flexDirection: "row", gap: 10, alignItems: "flex-start" },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: T.muted, marginTop: 9 },
  tipText: { flex: 1, fontSize: 16, color: T.ink2, lineHeight: 22 }
});

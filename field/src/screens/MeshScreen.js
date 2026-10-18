// 7. Mesh and QR: what this phone carries, and passing it to another phone by QR code. Each
// code is one signed packet; the other phone checks it and keeps it until it can reach the
// command post (or meets a phone that can). Bluetooth relay needs the development build (README).
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import QRCode from "react-native-qrcode-svg";
import { useApp } from "../shell/AppState";
import QrScanner from "../shell/QrScanner";
import { Muted, Notice, Pill, Screen, Section, T } from "../shell/ui";
import Icon from "../shell/Icon";
import { fromQr, receive, toQr } from "../core/mesh.js";
import { label } from "../core/rules.js";

export default function MeshScreen({ back }) {
  const { store, settings, counts, syncNow } = useApp();
  const [mode, setMode] = useState(null); // "show" | "scan"
  const [i, setI] = useState(0);
  const [log, setLog] = useState([]);
  const packets = store.valid().filter((r) => !r.delivered || ["alert", "job", "revoke"].includes(r.kind));

  // Show the packets one after another, most urgent first.
  useEffect(() => {
    if (mode !== "show" || !packets.length) return undefined;
    const t = setInterval(() => setI((n) => (n + 1) % packets.length), 2500);
    return () => clearInterval(t);
  }, [mode, packets.length]);

  function scanned(text) {
    const wire = fromQr(text);
    if (!wire) {
      setLog((l) => [{ ok: false, text: "Not a Pulse packet" }, ...l].slice(0, 8));
      return;
    }
    const added = receive(store, [wire], { commandPostKey: settings.sign_pk });
    store.save();
    setLog((l) => [{ ok: !!added, text: added ? "Got 1 new message" : "Already have it (or it failed the check)" }, ...l].slice(0, 8));
    if (added) syncNow();
  }

  const current = packets[i % Math.max(1, packets.length)];
  return (
    <Screen title="Mesh and QR" subtitle="Pass messages phone to phone" onBack={() => {setMode(null);back();}}>
      <View style={styles.stats}>
        <View style={styles.stat}><Text style={styles.statNum}>{counts.total}</Text><Text style={styles.statLabel}>messages carried</Text></View>
        <View style={[styles.stat, counts.waiting > 0 && styles.statWarn]}>
          <Text style={[styles.statNum, counts.waiting > 0 && { color: T.amber }]}>{counts.waiting}</Text>
          <Text style={styles.statLabel}>still need to reach the command post</Text>
        </View>
      </View>
      <Muted>When a phone with a connection gets them, they go on to the command post. Alerts travel the other way.</Muted>

      <View style={styles.segment} accessibilityRole="tablist">
        {[["show", "Show QR", "qr"], ["scan", "Scan QR", "scan"]].map(([m, t, icon]) => {
          const on = mode === m;
          return (
            <Pressable key={m} onPress={() => setMode(on ? null : m)} accessibilityRole="tab" accessibilityState={{ selected: on }}
            style={({ pressed }) => [styles.segBtn, on && styles.segOn, pressed && { opacity: 0.8 }]}>
              <Icon name={icon} size={22} color={on ? "#fff" : T.ink} />
              <Text style={[styles.segText, on && styles.segTextOn]}>{t}</Text>
            </Pressable>);
        })}
      </View>

      {mode === "show" && (
      current ?
      <View style={styles.qrCard}>
            <View style={styles.qrHead}>
              <Pill tone="info" label={`${i % packets.length + 1} of ${packets.length}`} />
              <Text style={styles.qrKind}>{label(current.kind)} · urgency {current.urgency}</Text>
            </View>
            <View style={styles.qrBox}><QRCode value={toQr(current.wire)} size={280} ecl="L" /></View>
            <Muted style={{ textAlign: "center" }}>Hold it in front of the other phone's Scan QR; codes change every 2.5 s.</Muted>
          </View> :
      <Notice tone="info" icon="check" title="Nothing to pass on">This phone has no messages to hand over right now.</Notice>)
      }
      {mode === "scan" && <QrScanner onCode={scanned} />}

      {log.length > 0 &&
      <Section title="Scanned">
          {log.map((line, n) =>
        <View key={n} style={styles.logRow}>
              <Icon name={line.ok ? "check" : "info"} size={18} color={line.ok ? T.green : T.muted} />
              <Text style={[styles.logText, n > 0 && { color: T.muted }]}>{line.text}</Text>
            </View>
        )}
        </Section>
      }

      <Section title="Bluetooth relay">
        <View style={styles.bt}>
          <Icon name="bluetooth" size={20} color={T.muted} />
          <Muted style={{ flex: 1 }}>Automatic phone-to-phone relay over Bluetooth and Wi-Fi Direct runs in the Pulse development build, not in Expo Go. The protocol is the same; see field/README.md.</Muted>
        </View>
      </Section>
    </Screen>);
}

const styles = StyleSheet.create({
  stats: { flexDirection: "row", gap: 10 },
  stat: { flex: 1, backgroundColor: T.panel, borderRadius: 12, borderWidth: 1, borderColor: T.line, padding: 14 },
  statWarn: { backgroundColor: T.amberSoft, borderColor: T.amberLine },
  statNum: { fontSize: 30, fontWeight: "800", color: T.ink, fontVariant: ["tabular-nums"] },
  statLabel: { fontSize: 14, color: T.muted, fontWeight: "600" },
  segment: { flexDirection: "row", gap: 8, backgroundColor: T.panel3, padding: 4, borderRadius: 12 },
  segBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 52, borderRadius: 9 },
  segOn: { backgroundColor: T.ink },
  segText: { fontSize: 17, fontWeight: "700", color: T.ink },
  segTextOn: { color: "#fff" },
  qrCard: { alignItems: "center", gap: 12, backgroundColor: T.panel, padding: 16, borderRadius: 14, borderWidth: 1, borderColor: T.line },
  qrHead: { flexDirection: "row", alignItems: "center", gap: 10, alignSelf: "stretch" },
  qrKind: { flex: 1, fontSize: 15, fontWeight: "700", color: T.ink2, textTransform: "capitalize" },
  qrBox: { padding: 12, backgroundColor: "#fff", borderRadius: 10 },
  logRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  logText: { flex: 1, fontSize: 15, color: T.ink },
  bt: { flexDirection: "row", gap: 10, alignItems: "flex-start" }
});

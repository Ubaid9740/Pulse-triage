// 7. Mesh and QR: what this phone carries, and passing it to another phone by QR code. Each
// code is one signed packet; the other phone checks it and keeps it until it can reach the
// command post (or meets a phone that can). Bluetooth relay needs the development build (README).
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import QRCode from "react-native-qrcode-svg";
import { useApp } from "../shell/AppState";
import QrScanner from "../shell/QrScanner";
import { Button, C, Muted, Row, Screen, Section } from "../shell/ui";
import { fromQr, receive, toQr } from "../core/mesh.js";
import { label } from "../core/rules.js";

export default function MeshScreen({ back }) {
  const { store, settings, counts, syncNow } = useApp();
  const [mode, setMode] = useState(null);           // "show" | "scan"
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
      setLog((l) => ["Not a Pulse packet", ...l].slice(0, 8));
      return;
    }
    const added = receive(store, [wire], { commandPostKey: settings.sign_pk });
    store.save();
    setLog((l) => [added ? "Got 1 new message" : "Already have it (or it failed the check)", ...l].slice(0, 8));
    if (added) syncNow();
  }

  const current = packets[i % Math.max(1, packets.length)];
  return (
    <Screen title="Mesh and QR" onBack={() => { setMode(null); back(); }}>
      <Section>
        <Text style={{ fontWeight: "700" }}>This phone carries {counts.total} messages; {counts.waiting} still need to reach the command post.</Text>
        <Muted>When a phone with a connection gets them, they go on to the command post. Alerts travel the other way.</Muted>
      </Section>
      <Row>
        <Button title="Show QR" kind={mode === "show" ? "dark" : "plain"} onPress={() => setMode(mode === "show" ? null : "show")} />
        <Button title="Scan QR" kind={mode === "scan" ? "dark" : "plain"} onPress={() => setMode(mode === "scan" ? null : "scan")} />
      </Row>
      {mode === "show" && (
        current ? (
          <View style={{ alignItems: "center", gap: 8, backgroundColor: "#fff", padding: 16, borderRadius: 14 }}>
            <QRCode value={toQr(current.wire)} size={280} ecl="L" />
            <Muted>{i % packets.length + 1} of {packets.length}: {label(current.kind)} · urgency {current.urgency}</Muted>
            <Muted>Hold it in front of the other phone's Scan QR; codes change every 2.5 s.</Muted>
          </View>
        ) : <Muted>Nothing to pass on.</Muted>
      )}
      {mode === "scan" && <QrScanner onCode={scanned} />}
      {log.map((line, n) => <Text key={n} style={{ color: n ? C.muted : C.ink }}>{line}</Text>)}
      <Section title="Bluetooth relay">
        <Muted>Automatic phone-to-phone relay over Bluetooth and Wi-Fi Direct runs in the Pulse development build, not in Expo Go. The protocol is the same; see field/README.md.</Muted>
      </Section>
    </Screen>
  );
}

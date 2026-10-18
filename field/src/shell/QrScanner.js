// A full-width camera that reads QR codes (expo-camera). onCode gets each new code's text.
import { useRef } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { Button, Notice } from "./ui";
import { T } from "./theme";

export default function QrScanner({ onCode, height = 320 }) {
  const [permission, requestPermission] = useCameraPermissions();
  const last = useRef({ text: null, at: 0 });
  if (!permission) {
    return (
      <View style={styles.wait}>
        <ActivityIndicator color={T.primary} />
        <Text style={styles.waitText}>Checking the camera…</Text>
      </View>);
  }
  if (!permission.granted) {
    return (
      <Notice tone="warning" icon="camera" title="Camera needed"
      action={<Button title="Allow the camera" icon="camera" onPress={requestPermission} kind="dark" />}>
        The camera is needed to scan QR codes.
      </Notice>);
  }
  return (
    <View style={[styles.frame, { height }]}>
      <CameraView style={StyleSheet.absoluteFill} facing="back" barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
      onBarcodeScanned={({ data }) => {
        const now = Date.now();
        if (data === last.current.text && now - last.current.at < 3000) return; // the same code, still in view
        last.current = { text: data, at: now };
        onCode(data);
      }} />
      <View style={styles.guide} pointerEvents="none">
        <View style={[styles.corner, styles.tl]} />
        <View style={[styles.corner, styles.tr]} />
        <View style={[styles.corner, styles.bl]} />
        <View style={[styles.corner, styles.br]} />
      </View>
      <View style={styles.caption} pointerEvents="none">
        <Text style={styles.captionText}>Point at the QR code</Text>
      </View>
    </View>);
}

const C = 28;
const styles = StyleSheet.create({
  frame: { borderRadius: 14, overflow: "hidden", backgroundColor: "#000" },
  guide: { position: "absolute", top: "14%", bottom: "20%", left: "14%", right: "14%" },
  corner: { position: "absolute", width: C, height: C, borderColor: "#FFFFFF" },
  tl: { top: 0, left: 0, borderTopWidth: 4, borderLeftWidth: 4, borderTopLeftRadius: 8 },
  tr: { top: 0, right: 0, borderTopWidth: 4, borderRightWidth: 4, borderTopRightRadius: 8 },
  bl: { bottom: 0, left: 0, borderBottomWidth: 4, borderLeftWidth: 4, borderBottomLeftRadius: 8 },
  br: { bottom: 0, right: 0, borderBottomWidth: 4, borderRightWidth: 4, borderBottomRightRadius: 8 },
  caption: { position: "absolute", left: 0, right: 0, bottom: 14, alignItems: "center" },
  captionText: { color: "#FFFFFF", fontSize: 15, fontWeight: "700", backgroundColor: "rgba(15,27,45,0.7)", paddingHorizontal: 12,
    paddingVertical: 6, borderRadius: 8, overflow: "hidden" },
  wait: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14 },
  waitText: { color: T.muted, fontSize: 15 }
});

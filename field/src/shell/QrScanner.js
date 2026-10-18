// A full-width camera that reads QR codes (expo-camera). onCode gets each new code's text.
import { useRef } from "react";
import { StyleSheet, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { Button, Muted } from "./ui";

export default function QrScanner({ onCode, height = 320 }) {
  const [permission, requestPermission] = useCameraPermissions();
  const last = useRef({ text: null, at: 0 });
  if (!permission) return <Muted>Checking the camera…</Muted>;
  if (!permission.granted) {
    return (
      <View style={{ gap: 8 }}>
        <Muted>The camera is needed to scan QR codes.</Muted>
        <Button title="Allow the camera" onPress={requestPermission} kind="dark" />
      </View>
    );
  }
  return (
    <View style={[styles.frame, { height }]}>
      <CameraView style={StyleSheet.absoluteFill} facing="back" barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
        onBarcodeScanned={({ data }) => {
          const now = Date.now();
          if (data === last.current.text && now - last.current.at < 3000) return;   // the same code, still in view
          last.current = { text: data, at: now };
          onCode(data);
        }} />
    </View>
  );
}

const styles = StyleSheet.create({ frame: { borderRadius: 14, overflow: "hidden", backgroundColor: "#000" } });

// Small shared building blocks: big touch targets, high contrast, readable outdoors.
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

export const C = {
  ink: "#1d2433", muted: "#5b6472", line: "#d9dee5", bg: "#f4f5f7", panel: "#ffffff",
  red: "#d64545", orange: "#e8892b", yellow: "#e9c53b", green: "#2e9d5b", blue: "#2f6fd6",
};
export const BAND = { watch: C.yellow, warning: C.orange, emergency: C.red };

export function Screen({ title, onBack, children, right }) {
  const isPulse = title === "Pulse" || (typeof title === "string" && title.startsWith("Pulse"));
  return (
    <View style={s.screen}>
      <View style={s.header}>
        {onBack ? <Pressable onPress={onBack} style={s.back} accessibilityLabel="Back"><Text style={s.backText}>‹</Text></Pressable> : null}
        {isPulse && (
          <Image
            source={require("../../assets/pulse-mark.png")}
            style={s.headerLogo}
            resizeMode="contain"
          />
        )}
        <Text style={s.title} numberOfLines={1}>{title}</Text>
        {right}
      </View>
      <ScrollView contentContainerStyle={s.body} keyboardShouldPersistTaps="handled">{children}</ScrollView>
    </View>
  );
}

export function Button({ title, onPress, kind = "plain", disabled, big, style }) {
  const colours = { plain: [C.panel, C.ink, "#b9c1cc"], primary: [C.red, "#fff", C.red], dark: [C.ink, "#fff", C.ink],
    green: [C.green, "#fff", C.green], blue: [C.blue, "#fff", C.blue] }[kind];
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button"
      style={({ pressed }) => [s.button, big && s.big, { backgroundColor: colours[0], borderColor: colours[2],
        opacity: disabled ? 0.45 : pressed ? 0.8 : 1 }, style]}>
      <Text style={[s.buttonText, big && s.bigText, { color: colours[1] }]}>{title}</Text>
    </Pressable>
  );
}

export function Chip({ label, on, onPress }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="checkbox" accessibilityState={{ checked: !!on }}
      style={[s.chip, on && s.chipOn]}>
      <Text style={[s.chipText, on && s.chipTextOn]}>{label}</Text>
    </Pressable>
  );
}

export function Section({ title, children }) {
  return (
    <View style={s.section}>
      {title ? <Text style={s.sectionTitle}>{title}</Text> : null}
      {children}
    </View>
  );
}

export const Row = ({ children, style }) => <View style={[s.row, style]}>{children}</View>;
export const Muted = ({ children, style }) => <Text style={[s.muted, style]}>{children}</Text>;
export const Err = ({ children }) => (children ? <Text style={s.error}>{children}</Text> : null);

export const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.bg },
  header: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 16, paddingTop: 44, paddingBottom: 12,
    backgroundColor: C.ink },
  headerLogo: { width: 26, height: 26, borderRadius: 6, marginRight: 2 },
  back: { paddingRight: 8 },
  backText: { color: "#fff", fontSize: 30, lineHeight: 30 },
  title: { color: "#fff", fontSize: 20, fontWeight: "700", flex: 1 },
  body: { padding: 16, gap: 14, paddingBottom: 40 },
  button: { paddingVertical: 12, paddingHorizontal: 16, borderRadius: 12, borderWidth: 1, alignItems: "center" },
  buttonText: { fontSize: 16, fontWeight: "700" },
  big: { paddingVertical: 22, borderRadius: 16 },
  bigText: { fontSize: 20 },
  chip: { paddingVertical: 9, paddingHorizontal: 14, borderRadius: 20, borderWidth: 1, borderColor: "#b9c1cc",
    backgroundColor: C.panel },
  chipOn: { backgroundColor: C.ink, borderColor: C.ink },
  chipText: { fontSize: 15, color: C.ink },
  chipTextOn: { color: "#fff", fontWeight: "700" },
  section: { backgroundColor: C.panel, borderRadius: 14, padding: 14, gap: 10, borderWidth: 1, borderColor: C.line },
  sectionTitle: { fontSize: 15, fontWeight: "700", color: C.muted },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" },
  muted: { color: C.muted, fontSize: 14 },
  error: { color: "#b42318", fontWeight: "700" },
  input: { borderWidth: 1, borderColor: "#b9c1cc", borderRadius: 10, padding: 12, fontSize: 16, backgroundColor: "#fff",
    color: C.ink },
});

// Small shared building blocks: big touch targets, high contrast, readable outdoors.
// Every screen builds from these, so spacing, type and colour stay the same everywhere.
import { useState } from "react";
import {
  ActivityIndicator, Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StatusBar, StyleSheet, Text,
  TextInput, View } from
"react-native";
import Icon from "./Icon";
import { RADIUS, T, TONES } from "./theme";

export { T, TONES };

// Kept for older imports: C.red / C.orange / C.yellow are the fill colours.
export const C = { ...T, red: T.redFill, orange: T.orangeFill, yellow: T.yellowFill, blue: T.primary };
export const BAND = { watch: T.yellowFill, warning: T.orangeFill, emergency: T.redFill };
export const BAND_INK = { watch: T.ink, warning: T.ink, emergency: "#FFFFFF" };

const TOP_INSET = Platform.OS === "android" ? StatusBar.currentHeight || 24 : Platform.OS === "ios" ? 48 : 0;

// A screen: light header (back, title, optional subtitle and right slot), scrolling body, and an
// optional footer that stays above the keyboard for the main action.
export function Screen({ title, subtitle, onBack, children, right, footer }) {
  const isPulse = title === "Pulse" || typeof title === "string" && title.startsWith("Pulse");
  return (
    <View style={s.screen}>
      <View style={[s.header, { paddingTop: TOP_INSET + 10 }]}>
        {onBack ?
        <Pressable onPress={onBack} style={({ pressed }) => [s.back, pressed && s.pressedSoft]} accessibilityRole="button"
        accessibilityLabel="Back" hitSlop={8}>
            <Icon name="chevronLeft" size={26} color={T.ink} />
          </Pressable> :
        null}
        {isPulse && <Image source={require("../../assets/pulse-mark.png")} style={s.headerLogo} resizeMode="contain" />}
        <View style={s.titleWrap}>
          <Text style={s.title} numberOfLines={1} accessibilityRole="header">{title}</Text>
          {subtitle ? <Text style={s.subtitle} numberOfLines={1}>{subtitle}</Text> : null}
        </View>
        {right}
      </View>
      <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView style={s.flex} contentContainerStyle={s.body} keyboardShouldPersistTaps="handled">{children}</ScrollView>
        {footer ? <View style={s.footer}>{footer}</View> : null}
      </KeyboardAvoidingView>
    </View>);

}

const KINDS = {
  plain: { bg: T.panel, fg: T.ink, border: T.lineStrong },
  primary: { bg: T.redFill, fg: "#FFFFFF", border: T.redFill }, // emergency actions
  dark: { bg: T.ink, fg: "#FFFFFF", border: T.ink },
  green: { bg: T.green, fg: "#FFFFFF", border: T.green },
  blue: { bg: T.primary, fg: "#FFFFFF", border: T.primary },
  soft: { bg: T.primarySoft, fg: T.primary, border: T.primaryLine },
  danger: { bg: T.panel, fg: T.red, border: T.redLine } // high-impact but not the main action
};

export function Button({ title, onPress, kind = "plain", disabled, big, style, icon, busy, subtitle, accessibilityLabel }) {
  const k = KINDS[kind] || KINDS.plain;
  const off = !!(disabled || busy);
  return (
    <Pressable onPress={onPress} disabled={off} accessibilityRole="button" accessibilityLabel={accessibilityLabel || title}
    accessibilityState={{ disabled: off, busy: !!busy }}
    style={({ pressed }) => [s.button, big && s.big, { backgroundColor: k.bg, borderColor: k.border, opacity: disabled ? 0.45 : 1 },
    pressed && !off && s.pressed, style]}>
      {busy ? <ActivityIndicator color={k.fg} /> : icon ? <Icon name={icon} size={big ? 26 : 20} color={k.fg} /> : null}
      <View style={s.buttonLabel}>
        <Text style={[s.buttonText, big && s.bigText, { color: k.fg }]} numberOfLines={2}>{title}</Text>
        {subtitle ? <Text style={[s.buttonSub, { color: k.fg }]} numberOfLines={2}>{subtitle}</Text> : null}
      </View>
    </Pressable>);

}

// A choice. `single` makes it read as a radio button to screen readers.
export function Chip({ label, on, onPress, single }) {
  return (
    <Pressable onPress={onPress} accessibilityRole={single ? "radio" : "checkbox"}
    accessibilityState={single ? { selected: !!on } : { checked: !!on }}
    style={({ pressed }) => [s.chip, on && s.chipOn, pressed && s.pressedSoft]}>
      {on ? <Icon name="check" size={16} color="#FFFFFF" strokeWidth={2.6} /> : null}
      <Text style={[s.chipText, on && s.chipTextOn]}>{label}</Text>
    </Pressable>);

}

export function Section({ title, hint, right, children, style }) {
  return (
    <View style={[s.section, style]}>
      {title || right ?
      <View style={s.sectionHead}>
          <View style={s.flexShrink}>
            {title ? <Text style={s.sectionTitle} accessibilityRole="header">{title}</Text> : null}
            {hint ? <Text style={s.sectionHint}>{hint}</Text> : null}
          </View>
          {right}
        </View> :
      null}
      {children}
    </View>);

}

// Status label: colour plus icon plus words, never colour alone.
export function Pill({ tone = "neutral", icon, label }) {
  const [fg, bg, border] = TONES[tone] || TONES.neutral;
  return (
    <View style={[s.pill, { backgroundColor: bg, borderColor: border }]}>
      {icon ? <Icon name={icon} size={14} color={fg} strokeWidth={2.4} /> : null}
      <Text style={[s.pillText, { color: fg }]} numberOfLines={1}>{label}</Text>
    </View>);

}

// A tinted message block for warnings, blocks and confirmations.
export function Notice({ tone = "info", icon = "info", title, children, action }) {
  const [fg, bg, border] = TONES[tone] || TONES.info;
  return (
    <View style={[s.notice, { backgroundColor: bg, borderColor: border }]} accessibilityRole={tone === "critical" ? "alert" : undefined}>
      <View style={s.noticeRow}>
        <Icon name={icon} size={22} color={fg} />
        <View style={s.noticeText}>
          {title ? <Text style={[s.noticeTitle, { color: fg }]}>{title}</Text> : null}
          {typeof children === "string" ? <Text style={s.noticeBody}>{children}</Text> : children}
        </View>
      </View>
      {action ? <View style={s.noticeAction}>{action}</View> : null}
    </View>);

}

export function Field({ label, hint, optional, children }) {
  return (
    <View style={s.field}>
      <Text style={s.fieldLabel}>{label}{optional ? <Text style={s.fieldOptional}>  optional</Text> : null}</Text>
      {children}
      {hint ? <Text style={s.fieldHint}>{hint}</Text> : null}
    </View>);

}

export function Input({ style, multiline, onFocus, onBlur, ...props }) {
  const [focus, setFocus] = useState(false);
  return (
    <TextInput placeholderTextColor={T.faint} multiline={multiline} {...props}
    onFocus={(e) => {setFocus(true);onFocus?.(e);}} onBlur={(e) => {setFocus(false);onBlur?.(e);}}
    style={[s.input, multiline && s.inputMulti, focus && s.inputFocus, style]} />);

}

// − value + with 56pt buttons; the caller keeps its own limits.
export function Stepper({ value, onMinus, onPlus, minusDisabled, label }) {
  return (
    <View style={s.stepper} accessibilityLabel={label ? `${label}: ${value}` : undefined}>
      <Pressable onPress={onMinus} disabled={minusDisabled} accessibilityRole="button" accessibilityLabel="One fewer"
      style={({ pressed }) => [s.stepBtn, minusDisabled && s.stepOff, pressed && s.pressedSoft]}>
        <Icon name="minus" size={26} color={T.ink} strokeWidth={2.6} />
      </Pressable>
      <Text style={s.stepValue}>{value}</Text>
      <Pressable onPress={onPlus} accessibilityRole="button" accessibilityLabel="One more"
      style={({ pressed }) => [s.stepBtn, pressed && s.pressedSoft]}>
        <Icon name="plus" size={26} color={T.ink} strokeWidth={2.6} />
      </Pressable>
    </View>);

}

// A full-width row that opens a screen: icon, title, short status, chevron.
export function ListAction({ icon, title, subtitle, onPress, tone = "neutral", right, first }) {
  const [fg, bg] = TONES[tone] || TONES.neutral;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={subtitle ? `${title}. ${subtitle}` : title}
    style={({ pressed }) => [s.listRow, !first && s.listDivider, pressed && s.listPressed]}>
      <View style={[s.listIcon, { backgroundColor: bg }]}><Icon name={icon} size={22} color={fg} /></View>
      <View style={s.listText}>
        <Text style={s.listTitle} numberOfLines={2}>{title}</Text>
        {subtitle ? <Text style={s.listSub} numberOfLines={2}>{subtitle}</Text> : null}
      </View>
      {right}
      <Icon name="chevronRight" size={20} color={T.faint} />
    </Pressable>);

}

// Label / value lines (device info, job facts).
export function Fact({ icon, label, value, strong }) {
  return (
    <View style={s.fact}>
      {icon ? <Icon name={icon} size={18} color={T.muted} /> : null}
      <Text style={s.factLabel}>{label}</Text>
      <Text style={[s.factValue, strong && s.factStrong]} numberOfLines={3}>{value}</Text>
    </View>);

}

export const Row = ({ children, style }) => <View style={[s.row, style]}>{children}</View>;
export const Muted = ({ children, style }) => <Text style={[s.muted, style]}>{children}</Text>;
export const Err = ({ children }) => children ?
<View style={s.errBox} accessibilityRole="alert" accessibilityLiveRegion="polite">
    <Icon name="alert" size={18} color={T.red} />
    <Text style={s.error}>{children}</Text>
  </View> :
null;

export const s = StyleSheet.create({
  flex: { flex: 1 },
  flexShrink: { flexShrink: 1 },
  screen: { flex: 1, backgroundColor: T.bg },
  header: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingBottom: 12, backgroundColor: T.panel,
    borderBottomWidth: 1, borderBottomColor: T.line },
  headerLogo: { width: 32, height: 32, borderRadius: 8, marginLeft: 4 },
  back: { width: 44, height: 44, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  titleWrap: { flex: 1, minWidth: 0, paddingLeft: 4 },
  title: { color: T.ink, fontSize: 20, fontWeight: "800", letterSpacing: -0.2 },
  subtitle: { color: T.muted, fontSize: 13, fontWeight: "600", marginTop: 1 },
  body: { padding: 16, gap: 14, paddingBottom: 40 },
  footer: { padding: 12, paddingBottom: Platform.OS === "ios" ? 28 : 14, backgroundColor: T.panel, borderTopWidth: 1, borderTopColor: T.line, gap: 8 },

  button: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, minHeight: 52, paddingVertical: 12,
    paddingHorizontal: 16, borderRadius: RADIUS.md, borderWidth: 1.5 },
  buttonLabel: { alignItems: "center", flexShrink: 1 },
  buttonText: { fontSize: 17, fontWeight: "700", textAlign: "center" },
  buttonSub: { fontSize: 13, fontWeight: "600", opacity: 0.9, marginTop: 2, textAlign: "center" },
  big: { minHeight: 72, paddingVertical: 16, borderRadius: RADIUS.lg },
  bigText: { fontSize: 20, fontWeight: "800" },
  pressed: { opacity: 0.88, transform: [{ scale: 0.985 }] },
  pressedSoft: { opacity: 0.75 },

  chip: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 46, paddingHorizontal: 14, borderRadius: 10, borderWidth: 1.5,
    borderColor: T.lineStrong, backgroundColor: T.panel },
  chipOn: { backgroundColor: T.primary, borderColor: T.primary },
  chipText: { fontSize: 16, color: T.ink, fontWeight: "600", textTransform: "capitalize" },
  chipTextOn: { color: "#FFFFFF", fontWeight: "700" },

  section: { backgroundColor: T.panel, borderRadius: RADIUS.md, padding: 16, gap: 12, borderWidth: 1, borderColor: T.line },
  sectionHead: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 10 },
  sectionTitle: { fontSize: 16, fontWeight: "800", color: T.ink },
  sectionHint: { fontSize: 14, color: T.muted, marginTop: 2, lineHeight: 19 },

  pill: { flexDirection: "row", alignItems: "center", gap: 5, minHeight: 28, paddingHorizontal: 10, borderRadius: 8, borderWidth: 1, alignSelf: "flex-start" },
  pillText: { fontSize: 13, fontWeight: "800" },

  notice: { borderRadius: RADIUS.md, borderWidth: 1, padding: 14, gap: 12 },
  noticeRow: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  noticeText: { flex: 1, gap: 3 },
  noticeTitle: { fontSize: 16, fontWeight: "800" },
  noticeBody: { fontSize: 15, color: T.ink2, lineHeight: 21 },
  noticeAction: { gap: 8 },

  field: { gap: 6 },
  fieldLabel: { fontSize: 15, fontWeight: "700", color: T.ink },
  fieldOptional: { fontSize: 13, fontWeight: "600", color: T.faint },
  fieldHint: { fontSize: 13, color: T.muted },
  input: { minHeight: 52, borderWidth: 1.5, borderColor: T.lineStrong, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12,
    fontSize: 17, backgroundColor: T.panel, color: T.ink },
  inputMulti: { minHeight: 96, textAlignVertical: "top" },
  inputFocus: { borderColor: T.primary },

  stepper: { flexDirection: "row", alignItems: "center", gap: 16 },
  stepBtn: { width: 56, height: 56, borderRadius: 12, borderWidth: 1.5, borderColor: T.lineStrong, backgroundColor: T.panel,
    alignItems: "center", justifyContent: "center" },
  stepOff: { opacity: 0.35 },
  stepValue: { fontSize: 30, fontWeight: "800", minWidth: 56, textAlign: "center", color: T.ink, fontVariant: ["tabular-nums"] },

  listRow: { flexDirection: "row", alignItems: "center", gap: 14, minHeight: 68, paddingVertical: 12, paddingHorizontal: 14 },
  listDivider: { borderTopWidth: 1, borderTopColor: T.line },
  listPressed: { backgroundColor: T.panel2 },
  listIcon: { width: 44, height: 44, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  listText: { flex: 1, gap: 2 },
  listTitle: { fontSize: 17, fontWeight: "700", color: T.ink },
  listSub: { fontSize: 14, color: T.muted },
  group: { backgroundColor: T.panel, borderRadius: RADIUS.md, borderWidth: 1, borderColor: T.line, overflow: "hidden" },

  fact: { flexDirection: "row", alignItems: "flex-start", gap: 10, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: T.line },
  factLabel: { width: 96, fontSize: 14, color: T.muted, fontWeight: "600", paddingTop: 1 },
  factValue: { flex: 1, fontSize: 16, color: T.ink, fontWeight: "600" },
  factStrong: { fontWeight: "800" },

  row: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" },
  muted: { color: T.muted, fontSize: 15, lineHeight: 21 },
  errBox: { flexDirection: "row", gap: 8, alignItems: "flex-start", padding: 12, borderRadius: 10, backgroundColor: T.redSoft,
    borderWidth: 1, borderColor: T.redLine },
  error: { flex: 1, color: T.red, fontWeight: "700", fontSize: 15 }
});

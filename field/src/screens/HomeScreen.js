// 2. Home: the latest alert, the big red report button, field tools, and the connection status.
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { activeAlerts, openJob, revoked, TEAM_ROLES, useApp } from "../shell/AppState";
import { BAND, BAND_INK, Button, ListAction, Muted, Notice, Pill, s as ui, Screen, Section, T } from "../shell/ui";
import Icon from "../shell/Icon";
import { label } from "../core/rules.js";

function ago(date) {
  if (!date) return "never";
  const min = Math.round((Date.now() - new Date(date).getTime()) / 60000);
  return min < 1 ? "just now" : `${min} min ago`;
}

export default function HomeScreen({ go }) {
  const { settings, store, status, counts, syncNow } = useApp();
  const [syncing, setSyncing] = useState(false);
  const alerts = activeAlerts(store);
  const alert = alerts[0];
  const job = openJob(store, settings);
  const team = TEAM_ROLES.includes(settings.role);
  const verified = Boolean(settings.sign_pk && settings.box_pk);
  const blocked = revoked(store, settings);

  async function sync() {
    setSyncing(true);
    try {
      await syncNow();
    } catch {
      // the status card shows the link's own error
    } finally {
      setSyncing(false);
    }
  }

  const tools = [];
  if (team && verified) {
    tools.push({ key: "jobs", icon: "navigation", tone: job ? "info" : "neutral",
      title: job ? `Job ${job.job_id}: ${job.summary}` : "Jobs",
      subtitle: job ? `Now: ${label(settings.jobStatus?.[job.job_id] || "assigned")} · tap to update` : "None yet",
      onPress: () => go("jobs") });
  }
  if (settings.role !== "helper" && verified) {
    tools.push({ key: "welfare", icon: "userCheck", tone: "success", title: "I checked on someone",
      subtitle: "Welfare check: safe, needs help or not found", onPress: () => go("welfare") });
  }
  tools.push({ key: "mesh", icon: "qr", tone: "neutral", title: "Mesh and QR",
    subtitle: `Pass messages phone to phone · ${counts.waiting} waiting`, onPress: () => go("mesh") });

  return (
    <Screen title="Pulse" subtitle={`${label(settings.role)}${settings.name ? ` · ${settings.name}` : ""}`}
    right={<Pill tone={status.online ? "success" : "warning"} icon={status.online ? "wifi" : "wifiOff"} label={status.online ? "Online" : "Offline"} />}>
      {blocked &&
      <Notice tone="critical" icon="ban" title="This phone is blocked">
          The command post has blocked this phone. Its reports are refused.
        </Notice>
      }

      {alert ?
      <Pressable onPress={() => go("alert", { id: alert.alert_id })} accessibilityRole="button"
      accessibilityLabel={`Alert: ${alert.headline?.en || ""}. Open the alert.`}
      style={({ pressed }) => [styles.alert, pressed && ui.pressed]}>
          <View style={[styles.band, { backgroundColor: alert.cancel ? T.green : BAND[alert.severity] }]}>
            <Icon name={alert.cancel ? "check" : "bell"} size={20} color={alert.cancel ? "#fff" : BAND_INK[alert.severity]} strokeWidth={2.4} />
            <Text style={[styles.bandText, { color: alert.cancel ? "#fff" : BAND_INK[alert.severity] }]}>
              {alert.cancel ? "ALL CLEAR" : `${label(alert.hazard)} ${alert.severity}`.toUpperCase()}
            </Text>
            {alerts.length > 1 ? <Text style={[styles.bandMore, { color: alert.cancel ? "#fff" : BAND_INK[alert.severity] }]}>+{alerts.length - 1} more</Text> : null}
          </View>
          <View style={styles.alertBody}>
            <Text style={styles.headline}>{alert.headline?.en}</Text>
            <View style={styles.alertFoot}>
              <Icon name="mapPin" size={16} color={T.muted} />
              <Text style={styles.zones} numberOfLines={2}>{alert.zones.join(", ")}</Text>
              <Text style={styles.open}>Open</Text>
              <Icon name="chevronRight" size={18} color={T.primary} />
            </View>
          </View>
        </Pressable> :

      <View style={styles.noAlert}>
          <Icon name="bell" size={22} color={T.faint} />
          <Text style={styles.noAlertText}>No active alert. Alerts from the command post appear here and buzz the phone.</Text>
        </View>
      }

      <Button big kind="primary" icon="lifebuoy" title="Report someone who needs help"
      subtitle="Saved on this phone first, even with no signal"
      onPress={() => go("report", { hazard: alert?.hazard, alertId: alert?.alert_id })} />

      {team && !verified &&
      <Notice tone="warning" icon="lock" title="Command post QR scan required"
      action={<Button title="Verify device in Settings" icon="shield" onPress={() => go("settings")} />}>
          Scan the command post setup QR to receive authentic keys and unlock Jobs and Welfare checks.
        </Notice>
      }

      <View style={ui.group}>
        {tools.map(({ key, ...t }, i) => <ListAction key={key} first={i === 0} {...t} />)}
      </View>

      <Section title="Connection" right={<Pill tone={status.online ? "success" : "warning"} icon={status.online ? "wifi" : "wifiOff"}
      label={status.online ? "Connected" : "No connection"} />}>
        <Text style={styles.connLine}>
          {status.online ? "Connected to the command post" : "No connection: messages wait on this phone"}
        </Text>
        <View style={styles.stats}>
          <View style={styles.stat}><Text style={[styles.statNum, counts.waiting > 0 && !status.online && { color: T.amber }]}>{counts.waiting}</Text><Text style={styles.statLabel}>waiting to send</Text></View>
          <View style={styles.stat}><Text style={styles.statNum}>{counts.total}</Text><Text style={styles.statLabel}>carried</Text></View>
          <View style={styles.stat}><Text style={styles.statNumSmall}>{ago(status.lastSync)}</Text><Text style={styles.statLabel}>last sync</Text></View>
        </View>
        {status.error ? <Muted>{status.error}</Muted> : null}
        <Button title={syncing ? "Syncing…" : "Sync now"} icon="refresh" busy={syncing} onPress={sync} />
      </Section>

      <View style={ui.group}>
        <ListAction first icon="settings" title="Settings" subtitle="This phone, command post, set up again" onPress={() => go("settings")} />
      </View>
      <Muted style={styles.device}>This phone: {settings.device}{settings.name ? ` · ${settings.name}` : ""}{settings.team_id ? ` · team ${settings.team_id}` : ""}</Muted>
    </Screen>);
}

const styles = StyleSheet.create({
  alert: { borderRadius: 14, overflow: "hidden", borderWidth: 1, borderColor: T.line, backgroundColor: T.panel },
  band: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 14, paddingVertical: 12 },
  bandText: { fontWeight: "900", fontSize: 16, letterSpacing: 0.4, flex: 1 },
  bandMore: { fontWeight: "700", fontSize: 13 },
  alertBody: { padding: 14, gap: 10 },
  headline: { fontSize: 20, fontWeight: "800", color: T.ink, lineHeight: 26 },
  alertFoot: { flexDirection: "row", alignItems: "center", gap: 6 },
  zones: { flex: 1, color: T.muted, fontSize: 14 },
  open: { color: T.primary, fontWeight: "800", fontSize: 15 },
  noAlert: { flexDirection: "row", gap: 12, alignItems: "center", padding: 14, borderRadius: 12, borderWidth: 1, borderColor: T.line,
    borderStyle: "dashed", backgroundColor: T.panel },
  noAlertText: { flex: 1, color: T.muted, fontSize: 15, lineHeight: 21 },
  connLine: { fontSize: 15, fontWeight: "600", color: T.ink2 },
  stats: { flexDirection: "row", gap: 8 },
  stat: { flex: 1, backgroundColor: T.panel2, borderRadius: 10, paddingVertical: 10, paddingHorizontal: 10 },
  statNum: { fontSize: 24, fontWeight: "800", color: T.ink, fontVariant: ["tabular-nums"] },
  statNumSmall: { fontSize: 16, fontWeight: "800", color: T.ink, paddingTop: 5, paddingBottom: 3 },
  statLabel: { fontSize: 13, color: T.muted, fontWeight: "600" },
  device: { fontSize: 13, textAlign: "center" }
});

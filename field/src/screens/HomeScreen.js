// 2. Home: the latest alert, the big red report button, and the status line.
import { Pressable, Text, View } from "react-native";
import { activeAlerts, openJob, revoked, TEAM_ROLES, useApp } from "../shell/AppState";
import { BAND, Button, C, Muted, Screen, Section } from "../shell/ui";
import { label } from "../core/rules.js";

function ago(date) {
  if (!date) return "never";
  const min = Math.round((Date.now() - new Date(date).getTime()) / 60000);
  return min < 1 ? "just now" : `${min} min ago`;
}

export default function HomeScreen({ go }) {
  const { settings, store, status, counts, syncNow } = useApp();
  const alerts = activeAlerts(store);
  const alert = alerts[0];
  const job = openJob(store, settings);
  const team = TEAM_ROLES.includes(settings.role);

  return (
    <Screen title="PulseTriage" right={<Text style={{ color: "#fff" }}>{label(settings.role)}</Text>}>
      {revoked(store, settings) && (
        <Section><Text style={{ color: C.red, fontWeight: "700" }}>The command post has blocked this phone. Its reports are refused.</Text></Section>
      )}
      {alert ? (
        <Pressable onPress={() => go("alert", { id: alert.alert_id })} accessibilityRole="button">
          <View style={{ borderRadius: 14, overflow: "hidden", borderWidth: 1, borderColor: C.line }}>
            <Text style={{ backgroundColor: alert.cancel ? C.green : BAND[alert.severity], padding: 12, fontWeight: "800", fontSize: 16 }}>
              {alert.cancel ? "ALL CLEAR" : `${label(alert.hazard)} ${alert.severity}`.toUpperCase()}
            </Text>
            <View style={{ backgroundColor: "#fff", padding: 12, gap: 4 }}>
              <Text style={{ fontSize: 18, fontWeight: "700" }}>{alert.headline?.en}</Text>
              <Muted>{alert.zones.join(", ")} · tap to open</Muted>
            </View>
          </View>
        </Pressable>
      ) : (
        <Section><Muted>No active alert. Alerts from the command post appear here and buzz the phone.</Muted></Section>
      )}

      <Button big kind="primary" title="Report someone who needs help" onPress={() => go("report", { hazard: alert?.hazard, alertId: alert?.alert_id })} />

      {team && (
        <Button title={job ? `Job ${job.job_id}: ${job.summary}` : "Jobs (none yet)"} kind={job ? "blue" : "plain"} onPress={() => go("jobs")} />
      )}
      {settings.role !== "helper" && <Button title="I checked on someone (welfare check)" onPress={() => go("welfare")} />}
      <Button title="Mesh and QR: pass messages phone to phone" onPress={() => go("mesh")} />

      <Section>
        <Text style={{ fontWeight: "700", color: status.online ? C.green : C.orange }}>
          {status.online ? "Connected to the command post" : "No connection: messages wait on this phone"}
        </Text>
        <Muted>{counts.waiting} message{counts.waiting === 1 ? "" : "s"} waiting · {counts.total} carried · last sync {ago(status.lastSync)}</Muted>
        {status.error ? <Muted>{status.error}</Muted> : null}
        <Button title="Sync now" onPress={() => syncNow()} />
      </Section>
      <Muted>This phone: {settings.device}{settings.name ? ` · ${settings.name}` : ""}{settings.team_id ? ` · team ${settings.team_id}` : ""}</Muted>
      <Button title="Settings" onPress={() => go("settings")} />
    </Screen>
  );
}

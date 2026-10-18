// 6. Jobs (volunteers and rescue teams): the job, its distance, conditions and first-aid tips;
// On my way, Arrived, Done (the outcome form) and Can't reach; Ready, Out of service and fuel.
import { useEffect, useState } from "react";
import { Alert as Confirm, StyleSheet, Text, View } from "react-native";
import { jobsFor, openJob, useApp } from "../shell/AppState";
import { Button, Chip, Err, Fact, Field, Input, Muted, Notice, Pill, Row, Screen, Section, Stepper, T } from "../shell/ui";
import Icon from "../shell/Icon";
import { label } from "../core/rules.js";
import { distanceM } from "../core/packet.js";
import { ack } from "../core/payloads.js";

const STEPS = [["assigned", "Assigned"], ["en_route", "On my way"], ["arrived", "Arrived"], ["done", "Done"]];

export default function JobsScreen({ back }) {
  const { store, settings, saveSettings, send, position, sendPing } = useApp();
  const job = openJob(store, settings);
  const past = jobsFor(store, settings).filter((j) => j !== job);
  const [where, setWhere] = useState(null);
  const [outcome, setOutcome] = useState(null); // the Done form
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null); // the status being sent
  const [pinging, setPinging] = useState(false);
  const step = job ? settings.jobStatus?.[job.job_id] || "assigned" : null;
  const verified = Boolean(settings?.sign_pk && settings?.box_pk);

  // Hooks run before any early return (the verification screen below), always in the same order.
  useEffect(() => {
    if (!verified) return undefined;
    position().then(setWhere).catch(() => {});
    const t = setInterval(() => position().then(setWhere).catch(() => {}), 20000);
    return () => clearInterval(t);
  }, [position, verified]);

  const away = job && where && job.lat != null ? distanceM(where.lat, where.lng, job.lat, job.lng) : null;

  async function mark(status, extra = {}) {
    setError(null);
    setBusy(status);
    try {
      if (!settings.team_id) throw new Error("The command post has not linked this phone to a team yet: sync first.");
      await send("ack", ack({ teamId: settings.team_id, jobId: job?.job_id ?? null, status, ...extra }), { urgency: 3 });
      const jobStatus = job ? { ...settings.jobStatus, [job.job_id]: status } : settings.jobStatus;
      const teamStatus = status === "ready" ? "available" : status === "out_of_service" ? "out_of_service" : settings.teamStatus;
      await saveSettings({ ...settings, jobStatus, teamStatus });
      if (["en_route", "arrived"].includes(status)) sendPing(status === "arrived" ? "on_scene" : "en_route").catch(() => {});
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  // Arrived is also automatic: a ping from within 100 m puts the team on scene on the server.
  useEffect(() => {
    if (verified && job && step === "en_route" && away !== null && away <= 100) mark("arrived");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [away, step]);

  if (!verified) {
    return (
      <Screen title="Jobs" onBack={back}>
        <Notice tone="warning" icon="lock" title="Command post QR scan required"
        action={<Button title="Back to home" icon="home" onPress={back} />}>
          You must scan the Command Post setup QR code to receive authentic signing and encryption keys before unlocking team jobs.
        </Notice>
      </Screen>);
  }

  const stepIndex = STEPS.findIndex(([k]) => k === step);
  const confirmCantReach = () => Confirm.alert("Can't reach this job?", "The command post will be told and may give it to another team.",
  [{ text: "Cancel", style: "cancel" }, { text: "Can't reach", style: "destructive", onPress: () => mark("cant_reach", { reason: reason.trim() || "can't reach" }) }]);
  const confirmOut = () => Confirm.alert("Go out of service?", "The command post stops giving this team jobs until you tap Ready.",
  [{ text: "Cancel", style: "cancel" }, { text: "Out of service", style: "destructive", onPress: () => mark("out_of_service", { reason: reason.trim() || "out of service" }) }]);

  return (
    <Screen title="Jobs" subtitle={settings.team_id ? `Team ${settings.team_id}` : "Not linked to a team yet"} onBack={back}>
      {!settings.team_id &&
      <Notice tone="info" icon="link" title="Waiting for the command post">
          Waiting for the command post to add this phone as a team (it happens on the first sync).
        </Notice>
      }
      {job ?
      <View style={styles.job}>
          <View style={styles.jobHead}>
            <Text style={styles.jobId}>Job {job.job_id} · case #{job.case_id}</Text>
            <Pill tone={step === "arrived" ? "success" : "info"} icon={step === "arrived" ? "check" : "navigation"} label={`Now: ${label(step)}`} />
          </View>
          <View style={styles.jobBody}>
            <Text style={styles.summary}>{job.summary}</Text>
            {job.landmark ?
          <View style={styles.landmark}><Icon name="mapPin" size={20} color={T.primary} /><Text style={styles.landmarkText}>{job.landmark}</Text></View> :
          null}

            <View style={styles.progress} accessibilityLabel={`Progress: ${label(step)}`}>
              {STEPS.map(([k, t], i) =>
            <View key={k} style={styles.progressItem}>
                  <View style={[styles.progressBar, i <= stepIndex && styles.progressOn]} />
                  <Text style={[styles.progressText, i === stepIndex && styles.progressTextOn]}>{t}</Text>
                </View>
            )}
            </View>

            <View>
              <Fact icon="users" label="People" value={`${job.people} · ${job.conditions.map(label).join(", ") || "no conditions given"}`} />
              <Fact icon="navigation" label="Distance" value={away !== null ? `${(away / 1000).toFixed(1)} km away` : "distance unknown"} strong />
              <Fact icon="clock" label="ETA" value={new Date(job.eta).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} />
              {job.place ? <Fact icon="home" label="Take them to" value={job.place.name} strong /> : null}
            </View>

            {(job.first_aid || []).length > 0 &&
          <View style={styles.firstAid}>
                <Text style={styles.firstAidTitle}>First aid</Text>
                {job.first_aid.map((t, i) =>
            <View key={i} style={styles.tip}><View style={styles.dot} /><Text style={styles.tipText}>{t}</Text></View>
            )}
              </View>
          }

            {outcome ?
          <View style={styles.outcome}>
                <Text style={styles.outcomeTitle}>Job outcome</Text>
                <Field label="People helped">
                  <Stepper label="People helped" value={outcome.people} minusDisabled={outcome.people <= 0}
              onMinus={() => setOutcome((o) => ({ ...o, people: Math.max(0, o.people - 1) }))}
              onPlus={() => setOutcome((o) => ({ ...o, people: o.people + 1 }))} />
                </Field>
                <Field label="Taken to">
                  <Row>{[...(job.place ? [[job.place.id, job.place.name]] : []), ["hospital", "Hospital"], ["stayed", "Stayed"]].map(([v, t]) =>
                <Chip single key={v} label={t} on={outcome.to === v} onPress={() => setOutcome((o) => ({ ...o, to: v }))} />)}</Row>
                </Field>
                <Button big kind="green" icon="check" title="Send: done" busy={busy === "done"}
            onPress={() => {mark("done", { outcome: { people_helped: outcome.people, taken_to: outcome.to, supplies_used: {} } });setOutcome(null);}} />
                <Button title="Back to the job" onPress={() => setOutcome(null)} />
              </View> :

          <View style={styles.actions}>
                <Button big={step === "assigned"} kind="blue" icon="navigation" title="On my way" busy={busy === "en_route"}
            onPress={() => mark("en_route")} disabled={step !== "assigned" || !!busy} />
                <Button big={step === "en_route"} kind="dark" icon="mapPin" title="Arrived" busy={busy === "arrived"}
            onPress={() => mark("arrived")} disabled={step === "arrived" || !!busy} />
                <Button big={step === "arrived"} kind="green" icon="check" title="Done"
            onPress={() => setOutcome({ people: job.people, to: job.place?.id || "stayed" })} disabled={!!busy} />
                <View style={styles.cant}>
                  <Field label="Can't reach it?" optional hint="Say why, then tap Can't reach">
                    <Input value={reason} onChangeText={setReason} placeholder="e.g. road under water" />
                  </Field>
                  <Button kind="danger" icon="x" title="Can't reach" busy={busy === "cant_reach"} disabled={!!busy} onPress={confirmCantReach} />
                </View>
              </View>
          }
          </View>
        </View> :

      <View style={styles.empty}>
          <Icon name="navigation" size={28} color={T.faint} />
          <Text style={styles.emptyTitle}>No open job</Text>
          <Muted style={{ textAlign: "center" }}>Jobs from the command post appear here; keep the app open so your position is sent.</Muted>
        </View>
      }

      <Err>{error}</Err>

      <Section title="Team status" hint="Tell the command post what this team can do.">
        <Field label="Fuel">
          <Row>{["full", "half", "low"].map((f) => <Chip single key={f} label={f} on={settings.fuel === f} onPress={() => saveSettings({ ...settings, fuel: f })} />)}</Row>
        </Field>
        <Button title={pinging ? "Sending position…" : "Send my position now"} icon="crosshair" busy={pinging}
        onPress={() => {setPinging(true);sendPing().then((ok) => !ok && setError("No GPS or no team yet.")).catch((e) => setError(e.message)).finally(() => setPinging(false));}} />
        <Button kind="green" icon="check" title="Ready (available)" busy={busy === "ready"} disabled={!!busy} onPress={() => mark("ready")} />
        <View style={styles.outBox}>
          <Field label="Reason for out of service">
            <Input value={reason} onChangeText={setReason} placeholder="Engine fault, refuelling, crew resting" />
          </Field>
          <Button kind="primary" icon="power" title="Out of service" busy={busy === "out_of_service"} disabled={!!busy} onPress={confirmOut} />
        </View>
      </Section>

      {past.length > 0 && <Muted>Earlier jobs: {past.map((j) => j.job_id).join(", ")}</Muted>}
    </Screen>);
}

const styles = StyleSheet.create({
  job: { borderRadius: 14, overflow: "hidden", borderWidth: 1, borderColor: T.primaryLine, backgroundColor: T.panel },
  jobHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap",
    paddingHorizontal: 16, paddingVertical: 12, backgroundColor: T.primarySoft },
  jobId: { fontSize: 14, fontWeight: "800", color: T.primary },
  jobBody: { padding: 16, gap: 14 },
  summary: { fontSize: 22, fontWeight: "800", color: T.ink, lineHeight: 28 },
  landmark: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
  landmarkText: { flex: 1, fontSize: 17, color: T.ink2, fontWeight: "600", lineHeight: 23 },
  progress: { flexDirection: "row", gap: 6 },
  progressItem: { flex: 1, gap: 6 },
  progressBar: { height: 6, borderRadius: 3, backgroundColor: T.line },
  progressOn: { backgroundColor: T.primary },
  progressText: { fontSize: 12, color: T.muted, fontWeight: "600" },
  progressTextOn: { color: T.primary, fontWeight: "800" },
  firstAid: { backgroundColor: T.redSoft, borderRadius: 12, padding: 12, gap: 6, borderWidth: 1, borderColor: T.redLine },
  firstAidTitle: { fontSize: 14, fontWeight: "900", color: T.red, letterSpacing: 0.3 },
  tip: { flexDirection: "row", gap: 10, alignItems: "flex-start" },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: T.red, marginTop: 9 },
  tipText: { flex: 1, fontSize: 16, color: T.ink, lineHeight: 22 },
  actions: { gap: 10 },
  cant: { gap: 8, marginTop: 6, paddingTop: 14, borderTopWidth: 1, borderTopColor: T.line },
  outcome: { gap: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: T.line },
  outcomeTitle: { fontSize: 17, fontWeight: "800", color: T.ink },
  empty: { alignItems: "center", gap: 8, padding: 24, borderRadius: 12, borderWidth: 1, borderStyle: "dashed", borderColor: T.lineStrong,
    backgroundColor: T.panel },
  emptyTitle: { fontSize: 17, fontWeight: "800", color: T.ink },
  outBox: { gap: 8, paddingTop: 12, borderTopWidth: 1, borderTopColor: T.line }
});

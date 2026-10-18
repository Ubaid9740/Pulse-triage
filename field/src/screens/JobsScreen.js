// 6. Jobs (volunteers and rescue teams): the job, its distance, conditions and first-aid tips;
// On my way, Arrived, Done (the outcome form) and Can't reach; Ready, Out of service and fuel.
import { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";
import { jobsFor, openJob, useApp } from "../shell/AppState";
import { Button, C, Chip, Err, Muted, Row, Screen, Section, s } from "../shell/ui";
import { label } from "../core/rules.js";
import { distanceM } from "../core/packet.js";
import { ack } from "../core/payloads.js";

export default function JobsScreen({ back }) {
  const { store, settings, saveSettings, send, position, sendPing } = useApp();
  const job = openJob(store, settings);
  const past = jobsFor(store, settings).filter((j) => j !== job);
  const [where, setWhere] = useState(null);
  const [outcome, setOutcome] = useState(null);         // the Done form
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const step = job ? settings.jobStatus?.[job.job_id] || "assigned" : null;

  useEffect(() => {
    position().then(setWhere).catch(() => {});
    const t = setInterval(() => position().then(setWhere).catch(() => {}), 20000);
    return () => clearInterval(t);
  }, [position]);

  const away = job && where && job.lat != null ? distanceM(where.lat, where.lng, job.lat, job.lng) : null;

  async function mark(status, extra = {}) {
    setError(null);
    try {
      if (!settings.team_id) throw new Error("The command post has not linked this phone to a team yet: sync first.");
      await send("ack", ack({ teamId: settings.team_id, jobId: job?.job_id ?? null, status, ...extra }), { urgency: 3 });
      const jobStatus = job ? { ...settings.jobStatus, [job.job_id]: status } : settings.jobStatus;
      const teamStatus = status === "ready" ? "available" : status === "out_of_service" ? "out_of_service" : settings.teamStatus;
      await saveSettings({ ...settings, jobStatus, teamStatus });
      if (["en_route", "arrived"].includes(status)) sendPing(status === "arrived" ? "on_scene" : "en_route").catch(() => {});
    } catch (e) {
      setError(e.message);
    }
  }

  // Arrived is also automatic: a ping from within 100 m puts the team on scene on the server.
  useEffect(() => {
    if (job && step === "en_route" && away !== null && away <= 100) mark("arrived");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [away, step]);

  return (
    <Screen title="Jobs" onBack={back}>
      {!settings.team_id && <Muted>Waiting for the command post to add this phone as a team (it happens on the first sync).</Muted>}
      {job ? (
        <Section title={`Job ${job.job_id} · case #${job.case_id}`}>
          <Text style={{ fontSize: 20, fontWeight: "800" }}>{job.summary}</Text>
          {job.landmark ? <Text style={{ fontSize: 16 }}>{job.landmark}</Text> : null}
          <Muted>{job.people} {job.people === 1 ? "person" : "people"} · {job.conditions.map(label).join(", ") || "no conditions given"}</Muted>
          <Muted>{away !== null ? `${(away / 1000).toFixed(1)} km away` : "distance unknown"} · ETA {new Date(job.eta).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</Muted>
          {job.place ? <Muted>Take them to: {job.place.name}</Muted> : null}
          {(job.first_aid || []).length > 0 && <View>{job.first_aid.map((t, i) => <Text key={i}>• {t}</Text>)}</View>}
          <Text style={{ fontWeight: "700", color: C.blue }}>Now: {label(step)}</Text>
          {outcome ? (
            <View style={{ gap: 8 }}>
              <Text style={{ fontWeight: "700" }}>People helped</Text>
              <Row>
                <Button title="−" onPress={() => setOutcome((o) => ({ ...o, people: Math.max(0, o.people - 1) }))} />
                <Text style={{ fontSize: 22, fontWeight: "800" }}>{outcome.people}</Text>
                <Button title="+" onPress={() => setOutcome((o) => ({ ...o, people: o.people + 1 }))} />
              </Row>
              <Text style={{ fontWeight: "700" }}>Taken to</Text>
              <Row>{[...(job.place ? [[job.place.id, job.place.name]] : []), ["hospital", "Hospital"], ["stayed", "Stayed"]].map(([v, t]) =>
                <Chip key={v} label={t} on={outcome.to === v} onPress={() => setOutcome((o) => ({ ...o, to: v }))} />)}</Row>
              <Button kind="green" title="Send: done" onPress={() => { mark("done", { outcome: { people_helped: outcome.people, taken_to: outcome.to, supplies_used: {} } }); setOutcome(null); }} />
            </View>
          ) : (
            <View style={{ gap: 8 }}>
              <Button kind="blue" title="On my way" onPress={() => mark("en_route")} disabled={step !== "assigned"} />
              <Button kind="dark" title="Arrived" onPress={() => mark("arrived")} disabled={step === "arrived"} />
              <Button kind="green" title="Done" onPress={() => setOutcome({ people: job.people, to: job.place?.id || "stayed" })} />
              <TextInput style={s.input} value={reason} onChangeText={setReason} placeholder="Why you can't reach it (for Can't reach)" />
              <Button title="Can't reach" onPress={() => mark("cant_reach", { reason: reason.trim() || "can't reach" })} />
            </View>
          )}
        </Section>
      ) : (
        <Section><Muted>No open job. Jobs from the command post appear here; keep the app open so your position is sent.</Muted></Section>
      )}
      <Section title="Team">
        <Text style={{ fontWeight: "700" }}>Fuel</Text>
        <Row>{["full", "half", "low"].map((f) => <Chip key={f} label={f} on={settings.fuel === f} onPress={() => saveSettings({ ...settings, fuel: f })} />)}</Row>
        <Button title="Send my position now" onPress={() => sendPing().then((ok) => !ok && setError("No GPS or no team yet.")).catch((e) => setError(e.message))} />
        <Button kind="green" title="Ready (available)" onPress={() => mark("ready")} />
        <TextInput style={s.input} value={reason} onChangeText={setReason} placeholder="Reason: engine fault, refuelling, crew resting" />
        <Button kind="primary" title="Out of service" onPress={() => mark("out_of_service", { reason: reason.trim() || "out of service" })} />
      </Section>
      <Err>{error}</Err>
      {past.length > 0 && <Muted>Earlier jobs: {past.map((j) => j.job_id).join(", ")}</Muted>}
    </Screen>
  );
}

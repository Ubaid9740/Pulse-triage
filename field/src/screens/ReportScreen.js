// 4. Report form: what's happening, for whom, how many, who they are, the disaster's own
// questions, a note, a landmark and GPS. Send saves it at once, even with no signal.
import { useEffect, useState } from "react";
import { Alert as Confirm, StyleSheet, Switch, Text, View } from "react-native";
import { useApp } from "../shell/AppState";
import { Button, Chip, Err, Field, Input, Muted, Notice, Pill, Row, Screen, Section, Stepper, T } from "../shell/ui";
import { label, questions, urgencyHint } from "../core/rules.js";
import { reportPayload } from "../core/payloads.js";

export default function ReportScreen({ params, back, setLeaveGuard }) {
  const { profiles, settings, send, position, status } = useApp();
  const hazards = Object.keys(profiles.profiles).sort();
  const [hazard, setHazard] = useState(params.hazard && hazards.includes(params.hazard) ? params.hazard : hazards.includes("flood") ? "flood" : hazards[0]);
  const [forWhom, setForWhom] = useState(params.forWhom || "neighbour");
  const [people, setPeople] = useState(1);
  const [conditions, setConditions] = useState([]);
  const [details, setDetails] = useState({});
  const [note, setNote] = useState("");
  const [landmark, setLandmark] = useState("");
  const [where, setWhere] = useState(null);
  const [locating, setLocating] = useState(true);
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    position().then(setWhere).catch(() => setWhere(null)).finally(() => setLocating(false));
  }, [position]);

  // Ask before Back throws away a half-filled report.
  const dirty = !sent && (note.trim() || landmark.trim() || conditions.length || Object.keys(details).length || people !== 1);
  useEffect(() => {
    if (!setLeaveGuard) return undefined;
    setLeaveGuard(dirty ? (pop) => {
      Confirm.alert("Discard this report?", "What you entered has not been sent yet.",
      [{ text: "Keep editing", style: "cancel" }, { text: "Discard", style: "destructive", onPress: pop }]);
      return true;
    } : null);
    return () => setLeaveGuard(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty]);

  const answer = (id, value) => setDetails((old) => {
    const next = { ...old };
    if (value === undefined || Array.isArray(value) && !value.length) delete next[id];else
    next[id] = value;
    return next;
  });
  const toggle = (list, setList, v) => setList(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  async function submit() {
    if (sending) return;
    setError(null);
    setSending(true);
    try {
      const payload = reportPayload({ hazard, forWhom, people, conditions, details, note: note.trim(),
        lat: where?.lat ?? null, lng: where?.lng ?? null, accuracy: where?.accuracy ?? null, landmark: landmark.trim(),
        role: settings.role === "rescue_team" ? "rescue_team" : settings.role === "volunteer" ? "volunteer" : "helper",
        alertId: params.alertId });
      await send("report", payload, { urgency: urgencyHint(profiles, hazard, details, conditions) });
      setSent(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  }

  function relocate() {
    setLocating(true);
    position().then(setWhere).catch(() => {}).finally(() => setLocating(false));
  }

  if (sent) {
    return (
      <Screen title="Report saved" onBack={back}>
        <Notice tone="success" icon="check" title="Saved on this phone">
          {status.online ?
          "This phone is connected: it is on its way to the command post." :
          "It goes to the command post as soon as this phone, or any phone it meets, has a connection."}
        </Notice>
        <Button title="Report someone else" icon="lifebuoy" onPress={() => {setSent(false);setNote("");setLandmark("");setDetails({});setConditions([]);setPeople(1);}} />
        <Button title="Back to home" icon="home" kind="dark" onPress={back} />
      </Screen>);

  }

  const hazardName = profiles.profiles[hazard]?.label?.en || label(hazard);
  return (
    <Screen title="Report someone who needs help" subtitle={`${hazardName} · ${people} ${people === 1 ? "person" : "people"}`} onBack={back}
    footer={
    <>
          <Err>{error}</Err>
          <Button big kind="primary" icon="send" title={sending ? "Saving…" : "Send"} busy={sending} onPress={submit} />
        </>
    }>
      <Section title="What's happening?">
        <Row>{hazards.map((h) => <Chip single key={h} label={profiles.profiles[h]?.label?.en || label(h)} on={hazard === h}
          onPress={() => {setHazard(h);setDetails({});}} />)}</Row>
      </Section>

      <Section title="Who needs help?">
        <Field label="For whom">
          <Row>{[["self", "Me"], ["neighbour", "A neighbour"], ["other", "Someone else"]].map(([v, t]) =>
            <Chip single key={v} label={t} on={forWhom === v} onPress={() => setForWhom(v)} />)}</Row>
        </Field>
        <Field label="How many people">
          <Stepper label="People" value={people} minusDisabled={people <= 1}
          onMinus={() => setPeople((n) => Math.max(1, n - 1))} onPlus={() => setPeople((n) => Math.min(500, n + 1))} />
        </Field>
        <Field label="Who are they?" hint="Tick all that apply">
          <Row>{(profiles.common.conditions || []).map((c) =>
            <Chip key={c} label={label(c)} on={conditions.includes(c)} onPress={() => toggle(conditions, setConditions, c)} />)}</Row>
        </Field>
      </Section>

      <Section title={`${hazardName} questions`} hint="Answer what you know">
        {questions(profiles, hazard).map((q) =>
        <View key={q.id} style={styles.question}>
            {q.type === "yesno" ?
          <View style={styles.yesno}>
                <Text style={styles.ask}>{q.ask.en}</Text>
                <View style={styles.switchWrap}>
                  <Text style={[styles.switchLabel, details[q.id] === true && { color: T.primary }]}>{details[q.id] === true ? "Yes" : "No / ?"}</Text>
                  <Switch value={details[q.id] === true} onValueChange={(v) => answer(q.id, v ? true : undefined)}
              trackColor={{ true: T.primary, false: T.lineStrong }} thumbColor="#FFFFFF" accessibilityLabel={q.ask.en} />
                </View>
              </View> :
          <Text style={styles.ask}>{q.ask.en}</Text>}
            {q.type === "choice" &&
          <Row>{q.options.map((o) => <Chip single key={o} label={label(o)} on={details[q.id] === o}
            onPress={() => answer(q.id, details[q.id] === o ? undefined : o)} />)}</Row>
          }
            {q.type === "multi" &&
          <Row>{q.options.map((o) => {
              const picked = details[q.id] || [];
              return <Chip key={o} label={label(o)} on={picked.includes(o)}
              onPress={() => answer(q.id, picked.includes(o) ? picked.filter((x) => x !== o) : [...picked, o])} />;
            })}</Row>
          }
          </View>
        )}
      </Section>

      <Section title="Where" right={locating ? <Pill tone="info" icon="crosshair" label="Locating…" /> :
      where ? <Pill tone="success" icon="crosshair" label={`GPS ±${where.accuracy} m`} /> :
      <Pill tone="warning" icon="crosshair" label="No GPS" />}>
        <Muted>
          {locating ? "Finding your position…" :
          where ? `GPS ${where.lat.toFixed(5)}, ${where.lng.toFixed(5)} (±${where.accuracy} m)` :
          "No GPS: add a landmark below so the team can find them."}
        </Muted>
        <Button title="Use my position again" icon="crosshair" busy={locating} onPress={relocate} />
        <Field label="Landmark" optional>
          <Input value={landmark} onChangeText={setLandmark} maxLength={200} placeholder="Behind the green mosque, house 14" returnKeyType="next" />
        </Field>
      </Section>

      <Section title="Anything else">
        <Field label="Note" optional hint={`${note.length}/500`}>
          <Input multiline value={note} onChangeText={setNote} maxLength={500} placeholder="e.g. oxygen tank half empty, 2nd floor" />
        </Field>
      </Section>
    </Screen>);

}

const styles = StyleSheet.create({
  question: { gap: 10, paddingVertical: 6, borderTopWidth: 1, borderTopColor: T.line, paddingTop: 12 },
  yesno: { flexDirection: "row", alignItems: "center", gap: 12 },
  ask: { flex: 1, fontSize: 16, fontWeight: "600", color: T.ink, lineHeight: 22 },
  switchWrap: { flexDirection: "row", alignItems: "center", gap: 8 },
  switchLabel: { fontSize: 14, fontWeight: "700", color: T.muted, minWidth: 48, textAlign: "right" }
});

// 4. Report form: what's happening, for whom, how many, who they are, the disaster's own
// questions, a note, a landmark and GPS. Send saves it at once, even with no signal.
import { useEffect, useState } from "react";
import { Switch, Text, TextInput, View } from "react-native";
import { useApp } from "../shell/AppState";
import { Button, C, Chip, Err, Muted, Row, Screen, Section, s } from "../shell/ui";
import { label, questions, urgencyHint } from "../core/rules.js";
import { reportPayload } from "../core/payloads.js";

export default function ReportScreen({ params, back }) {
  const { profiles, settings, send, position } = useApp();
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
  const [error, setError] = useState(null);

  useEffect(() => {
    position().then(setWhere).catch(() => setWhere(null)).finally(() => setLocating(false));
  }, [position]);

  const answer = (id, value) => setDetails((old) => {
    const next = { ...old };
    if (value === undefined || (Array.isArray(value) && !value.length)) delete next[id];
    else next[id] = value;
    return next;
  });
  const toggle = (list, setList, v) => setList(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  async function submit() {
    setError(null);
    try {
      const payload = reportPayload({ hazard, forWhom, people, conditions, details, note: note.trim(),
        lat: where?.lat ?? null, lng: where?.lng ?? null, accuracy: where?.accuracy ?? null, landmark: landmark.trim(),
        role: settings.role === "rescue_team" ? "rescue_team" : settings.role === "volunteer" ? "volunteer" : "helper",
        alertId: params.alertId });
      await send("report", payload, { urgency: urgencyHint(profiles, hazard, details, conditions) });
      setSent(true);
    } catch (e) {
      setError(e.message);
    }
  }

  if (sent) {
    return (
      <Screen title="Report saved" onBack={back}>
        <Section>
          <Text style={{ fontSize: 20, fontWeight: "800", color: C.green }}>Saved on this phone</Text>
          <Muted>It goes to the command post as soon as this phone, or any phone it meets, has a connection.</Muted>
        </Section>
        <Button title="Report someone else" onPress={() => { setSent(false); setNote(""); setLandmark(""); setDetails({}); setConditions([]); setPeople(1); }} />
        <Button title="Back to home" kind="dark" onPress={back} />
      </Screen>
    );
  }

  return (
    <Screen title="Report someone who needs help" onBack={back}>
      <Section title="What's happening?">
        <Row>{hazards.map((h) => <Chip key={h} label={profiles.profiles[h]?.label?.en || label(h)} on={hazard === h}
          onPress={() => { setHazard(h); setDetails({}); }} />)}</Row>
      </Section>
      <Section title="For whom?">
        <Row>{[["self", "Me"], ["neighbour", "A neighbour"], ["other", "Someone else"]].map(([v, t]) =>
          <Chip key={v} label={t} on={forWhom === v} onPress={() => setForWhom(v)} />)}</Row>
      </Section>
      <Section title="How many people?">
        <Row>
          <Button title="−" onPress={() => setPeople((n) => Math.max(1, n - 1))} style={{ minWidth: 56 }} />
          <Text style={{ fontSize: 26, fontWeight: "800", minWidth: 50, textAlign: "center" }}>{people}</Text>
          <Button title="+" onPress={() => setPeople((n) => Math.min(500, n + 1))} style={{ minWidth: 56 }} />
        </Row>
      </Section>
      <Section title="Who are they?">
        <Row>{(profiles.common.conditions || []).map((c) =>
          <Chip key={c} label={label(c)} on={conditions.includes(c)} onPress={() => toggle(conditions, setConditions, c)} />)}</Row>
      </Section>
      <Section title={`${profiles.profiles[hazard]?.label?.en || label(hazard)} questions`}>
        {questions(profiles, hazard).map((q) => (
          <View key={q.id} style={{ gap: 6 }}>
            <Text style={{ fontSize: 16, fontWeight: "600" }}>{q.ask.en}</Text>
            {q.type === "yesno" && (
              <Row><Switch value={details[q.id] === true} onValueChange={(v) => answer(q.id, v ? true : undefined)} />
                <Muted>{details[q.id] === true ? "Yes" : "No / don't know"}</Muted></Row>
            )}
            {q.type === "choice" && (
              <Row>{q.options.map((o) => <Chip key={o} label={label(o)} on={details[q.id] === o}
                onPress={() => answer(q.id, details[q.id] === o ? undefined : o)} />)}</Row>
            )}
            {q.type === "multi" && (
              <Row>{q.options.map((o) => {
                const picked = details[q.id] || [];
                return <Chip key={o} label={label(o)} on={picked.includes(o)}
                  onPress={() => answer(q.id, picked.includes(o) ? picked.filter((x) => x !== o) : [...picked, o])} />;
              })}</Row>
            )}
          </View>
        ))}
      </Section>
      <Section title="Anything else (optional)">
        <TextInput style={[s.input, { minHeight: 80 }]} multiline value={note} onChangeText={setNote} maxLength={500}
          placeholder="e.g. oxygen tank half empty, 2nd floor" />
        <TextInput style={s.input} value={landmark} onChangeText={setLandmark} maxLength={200}
          placeholder="Landmark: behind the green mosque, house 14" />
      </Section>
      <Section title="Where">
        <Muted>{locating ? "Finding your position…" : where ? `GPS ${where.lat.toFixed(5)}, ${where.lng.toFixed(5)} (±${where.accuracy} m)` : "No GPS: add a landmark above."}</Muted>
        <Button title="Use my position again" onPress={() => { setLocating(true); position().then(setWhere).finally(() => setLocating(false)); }} />
      </Section>
      <Err>{error}</Err>
      <Button big kind="primary" title="Send" onPress={submit} />
    </Screen>
  );
}

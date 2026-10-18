// Settings: what this phone knows about the command post, and starting over.
import { Alert as Confirm, Text } from "react-native";
import { useApp } from "../shell/AppState";
import { Button, Muted, Screen, Section } from "../shell/ui";
import { label } from "../core/rules.js";

export default function SettingsScreen({ back }) {
  const { settings, status, leave } = useApp();
  return (
    <Screen title="Settings" onBack={back}>
      <Section title="This phone">
        <Text>{settings.device} · {label(settings.role)}{settings.name ? ` · ${settings.name}` : ""}</Text>
        {settings.team_id ? <Muted>Team: {settings.team_id}</Muted> : null}
        {settings.skills?.length ? <Muted>Skills: {settings.skills.map(label).join(", ")}</Muted> : null}
      </Section>
      <Section title="Command post">
        {settings.servers.map((x) => <Text key={x}>{x}{status.base === x ? "  (in use)" : ""}</Text>)}
        <Muted>Alert key {settings.sign_pk.slice(0, 12)}… · {settings.zones.length} zones</Muted>
      </Section>
      <Button kind="primary" title="Set up again (new keys)" onPress={() => Confirm.alert("Set up again?",
        "This phone gets new keys and must scan the setup code again. Messages it carries are kept.",
        [{ text: "Cancel", style: "cancel" }, { text: "Set up again", style: "destructive", onPress: leave }])} />
    </Screen>
  );
}

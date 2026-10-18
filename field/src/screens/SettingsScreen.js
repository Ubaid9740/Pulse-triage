// Settings: what this phone knows about the command post, and starting over.
import { Alert as Confirm, StyleSheet, Text, View } from "react-native";
import { useApp } from "../shell/AppState";
import { Button, Fact, Muted, Pill, Screen, Section, T } from "../shell/ui";
import Icon from "../shell/Icon";
import { label } from "../core/rules.js";

export default function SettingsScreen({ back }) {
  const { settings, status, leave } = useApp();
  const verified = Boolean(settings.sign_pk && settings.box_pk);
  return (
    <Screen title="Settings" onBack={back}>
      <Section title="This phone">
        <View>
          <Fact label="Device" value={settings.device} />
          <Fact label="Role" value={label(settings.role)} />
          {settings.name ? <Fact label="Name" value={settings.name} /> : null}
          {settings.team_id ? <Fact label="Team" value={settings.team_id} /> : null}
          {settings.skills?.length ? <Fact label="Skills" value={settings.skills.map(label).join(", ")} /> : null}
        </View>
      </Section>
      <Section title="Command post" right={<Pill tone={verified ? "success" : "warning"} icon={verified ? "shield" : "lock"}
      label={verified ? "Keys verified" : "Not verified"} />}>
        {settings.servers.map((x) =>
        <View key={x} style={styles.server}>
            <Icon name={status.base === x ? "wifi" : "link"} size={18} color={status.base === x ? T.green : T.muted} />
            <Text style={styles.serverText} numberOfLines={1}>{x}</Text>
            {status.base === x ? <Pill tone="success" label="in use" /> : null}
          </View>
        )}
        {!settings.servers.length ? <Muted>No command post address saved.</Muted> : null}
        <Muted>Alert key {settings.sign_pk.slice(0, 12)}… · {settings.zones.length} zones</Muted>
      </Section>
      <Section title="Start over" hint="This phone gets new keys and must scan the setup code again. Messages it carries are kept.">
        <Button kind="danger" icon="refresh" title="Set up again (new keys)" onPress={() => Confirm.alert("Set up again?",
        "This phone gets new keys and must scan the setup code again. Messages it carries are kept.",
        [{ text: "Cancel", style: "cancel" }, { text: "Set up again", style: "destructive", onPress: leave }])} />
      </Section>
    </Screen>);

}

const styles = StyleSheet.create({
  server: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 40 },
  serverText: { flex: 1, fontSize: 15, color: T.ink, fontWeight: "600" }
});

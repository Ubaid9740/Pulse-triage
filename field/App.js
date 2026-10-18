// Pulse field app: setup, home, alert, report, welfare check, jobs, mesh and QR.
// Navigation is a small stack in state; Android's back button pops it. A screen with unsaved input
// can set a leave guard (setLeaveGuard) so Back asks before throwing the input away.
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, BackHandler, Image, Text, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { AppProvider, useApp } from "./src/shell/AppState";
import { T } from "./src/shell/theme";
import SetupScreen from "./src/screens/SetupScreen";
import HomeScreen from "./src/screens/HomeScreen";
import AlertScreen from "./src/screens/AlertScreen";
import ReportScreen from "./src/screens/ReportScreen";
import WelfareScreen from "./src/screens/WelfareScreen";
import JobsScreen from "./src/screens/JobsScreen";
import MeshScreen from "./src/screens/MeshScreen";
import SettingsScreen from "./src/screens/SettingsScreen";

const SCREENS = { home: HomeScreen, alert: AlertScreen, report: ReportScreen, welfare: WelfareScreen, jobs: JobsScreen,
  mesh: MeshScreen, settings: SettingsScreen };

function Router() {
  const { ready, settings } = useApp();
  const [stack, setStack] = useState([{ name: "home", params: {} }]);
  const guard = useRef(null); // (pop) => true when it handled leaving itself
  const pop = () => {guard.current = null;setStack((s) => s.length > 1 ? s.slice(0, -1) : s);};
  const go = (name, params = {}) => {guard.current = null;setStack((s) => [...s, { name, params }]);};
  const back = () => {
    if (guard.current && guard.current(pop)) return;
    pop();
  };
  const setLeaveGuard = (fn) => {guard.current = fn || null;};

  useEffect(() => {
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      if (stack.length > 1) {
        back();
        return true;
      }
      return false;
    });
    return () => sub.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stack.length]);

  if (!ready) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center", gap: 16, backgroundColor: T.bg }}>
        <Image source={require("./assets/pulse-mark.png")} style={{ width: 56, height: 56, borderRadius: 14 }} resizeMode="contain" />
        <ActivityIndicator size="large" color={T.primary} />
        <Text style={{ color: T.muted, fontSize: 15, fontWeight: "600" }}>Loading what this phone carries…</Text>
      </View>);

  }
  if (!settings) return <SetupScreen />;
  const top = stack[stack.length - 1];
  const Screen = SCREENS[top.name] || HomeScreen;
  return <Screen key={stack.length} params={top.params} go={go} back={back} setLeaveGuard={setLeaveGuard} />;
}

export default function App() {
  return (
    <AppProvider>
      <StatusBar style="dark" />
      <Router />
    </AppProvider>);

}

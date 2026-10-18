// PulseTriage field app: setup, home, alert, report, welfare check, jobs, mesh and QR.
// Navigation is a small stack in state; Android's back button pops it.
import { useEffect, useState } from "react";
import { ActivityIndicator, BackHandler, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { AppProvider, useApp } from "./src/shell/AppState";
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
  const go = (name, params = {}) => setStack((s) => [...s, { name, params }]);
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));

  useEffect(() => {
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      if (stack.length > 1) {
        back();
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, [stack.length]);

  if (!ready) return <View style={{ flex: 1, justifyContent: "center" }}><ActivityIndicator size="large" /></View>;
  if (!settings) return <SetupScreen />;
  const top = stack[stack.length - 1];
  const Screen = SCREENS[top.name] || HomeScreen;
  return <Screen key={stack.length} params={top.params} go={go} back={back} />;
}

export default function App() {
  return (
    <AppProvider>
      <StatusBar style="light" />
      <Router />
    </AppProvider>
  );
}

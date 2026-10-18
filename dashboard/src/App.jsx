import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api.js";
import TopBar from "./components/TopBar.jsx";
import MapView from "./components/MapView.jsx";
import CaseList from "./components/CaseList.jsx";
import CaseCard from "./components/CaseCard.jsx";
import ZoneCard from "./components/ZoneCard.jsx";
import BottomStrip from "./components/BottomStrip.jsx";
import AlertComposer from "./components/AlertComposer.jsx";
import IntakeForm from "./components/IntakeForm.jsx";
import PasteBox from "./components/PasteBox.jsx";
import TeamsPanel from "./components/TeamsPanel.jsx";
import WeightsPanel from "./components/WeightsPanel.jsx";
import ChaosPanel from "./components/ChaosPanel.jsx";
import SetupQR from "./components/SetupQR.jsx";
import ReplayPanel from "./components/ReplayPanel.jsx";

const POLL_MS = 2000;

// One snapshot in state, polled every 2 s (System Design 6.2). Components only read it; after a
// command they call refresh() so the screen updates at once. A failed poll keeps the last snapshot.
export default function App() {
  const [snap, setSnap] = useState(null);
  const [offline, setOffline] = useState(false);
  const [profiles, setProfiles] = useState(null);
  const [selected, setSelected] = useState(null); // {kind: "case", id} or {kind: "zone", name}
  const [dialog, setDialog] = useState(null);     // "alert" | "intake" | "paste" | "chaos" | "setup"
  const [view, setView] = useState("map");        // "map" or "teams" (Teams and resources)
  const [weightsOpen, setWeightsOpen] = useState(false);
  const [replay, setReplay] = useState(null);     // the scenario replay's status (GET /api/demo/replay)
  const busy = useRef(false);

  const again = useRef(false);

  const refresh = useCallback(async () => {
    if (busy.current) {               // a poll is on its way: fetch once more when it lands,
      again.current = true;           // so a command's change shows at once, not 2 s later
      return;
    }
    busy.current = true;
    try {
      do {
        again.current = false;
        setSnap(await get("/api/snapshot"));
        setOffline(false);
      } while (again.current);
    } catch {
      setOffline(true);
    } finally {
      busy.current = false;
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    get("/api/profiles").then(setProfiles).catch(() => {});
  }, []);

  // The replay's clock and cues: polled with the snapshot, separately so a slow one never blocks the other.
  const pollReplay = useCallback(() => get("/api/demo/replay").then(setReplay).catch(() => {}), []);
  useEffect(() => {
    pollReplay();
    const timer = setInterval(pollReplay, POLL_MS);
    return () => clearInterval(timer);
  }, [pollReplay]);
  const refreshAll = useCallback(() => { refresh(); pollReplay(); }, [refresh, pollReplay]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && setSelected(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!snap) {
    return <div className="loading">{offline ? "Server not reachable. Retrying…" : "Loading…"}</div>;
  }

  const ranked = snap.cases;
  const rankOf = (id) => ranked.findIndex((c) => c.id === id) + 1;
  const openCase = (id) => { setDialog(null); setView("map"); setSelected({ kind: "case", id }); };
  const onOpen = (what) => {
    if (what === "teams") setView((v) => (v === "teams" ? "map" : "teams"));
    else if (what === "weights") { setView("map"); setSelected(null); setWeightsOpen((o) => !o); }
    else setDialog(what);
  };
  const close = () => setDialog(null);

  return (
    <div className="app">
      <TopBar snap={snap} offline={offline} profiles={profiles} refresh={refresh} onOpen={onOpen}
              view={view} weightsOpen={weightsOpen} replay={replay} />
      {view === "teams" ? (
        <main className="resources-pane">
          <TeamsPanel snap={snap} profiles={profiles} refresh={refresh} onOpenCase={openCase} />
        </main>
      ) : (
      <main className="main">
        <section className="map-pane">
          <MapView snap={snap} selected={selected} onSelect={setSelected} />
        </section>
        <aside className="side-pane">
          {selected?.kind === "case" && (
            <CaseCard caseId={selected.id} rank={rankOf(selected.id)} rev={snap.rev}
                      onClose={() => setSelected(null)} refresh={refresh} />
          )}
          {selected?.kind === "zone" && (
            <ZoneCard name={selected.name} rev={snap.rev} onClose={() => setSelected(null)}
                      onOpenCase={(id) => setSelected({ kind: "case", id })} refresh={refresh} />
          )}
          {!selected && weightsOpen && <WeightsPanel refresh={refresh} onClose={() => setWeightsOpen(false)} />}
          {!selected && <CaseList cases={ranked} onSelect={(id) => setSelected({ kind: "case", id })} />}
        </aside>
      </main>
      )}
      <BottomStrip snap={snap} replay={replay} />
      {dialog === "alert" && <AlertComposer snap={snap} profiles={profiles} refresh={refresh} onClose={close} />}
      {dialog === "intake" && <IntakeForm snap={snap} profiles={profiles} refresh={refresh} onClose={close} onOpenCase={openCase} />}
      {dialog === "paste" && <PasteBox snap={snap} profiles={profiles} refresh={refresh} onClose={close} onOpenCase={openCase} />}
      {dialog === "chaos" && <ChaosPanel refresh={refresh} onClose={close} onOpenCase={openCase} />}
      {dialog === "setup" && <SetupQR onClose={close} />}
      {dialog === "replay" && <ReplayPanel replay={replay} refresh={refreshAll} onClose={close} />}
    </div>
  );
}

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

const POLL_MS = 2000;

// One snapshot in state, polled every 2 s (System Design 6.2). Components only read it; after a
// command they call refresh() so the screen updates at once. A failed poll keeps the last snapshot.
export default function App() {
  const [snap, setSnap] = useState(null);
  const [offline, setOffline] = useState(false);
  const [profiles, setProfiles] = useState(null);
  const [selected, setSelected] = useState(null); // {kind: "case", id} or {kind: "zone", name}
  const [dialog, setDialog] = useState(null);     // "alert" | "intake" | "paste"
  const busy = useRef(false);

  const refresh = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      setSnap(await get("/api/snapshot"));
      setOffline(false);
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
  const openCase = (id) => { setDialog(null); setSelected({ kind: "case", id }); };
  const close = () => setDialog(null);

  return (
    <div className="app">
      <TopBar snap={snap} offline={offline} profiles={profiles} refresh={refresh} onOpen={setDialog} />
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
          {!selected && <CaseList cases={ranked} onSelect={(id) => setSelected({ kind: "case", id })} />}
        </aside>
      </main>
      <BottomStrip snap={snap} />
      {dialog === "alert" && <AlertComposer snap={snap} profiles={profiles} refresh={refresh} onClose={close} />}
      {dialog === "intake" && <IntakeForm snap={snap} profiles={profiles} refresh={refresh} onClose={close} onOpenCase={openCase} />}
      {dialog === "paste" && <PasteBox snap={snap} profiles={profiles} refresh={refresh} onClose={close} onOpenCase={openCase} />}
    </div>
  );
}

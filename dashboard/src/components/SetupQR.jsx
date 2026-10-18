import { useEffect, useState } from "react";
import { get } from "../api.js";
import Dialog from "./Dialog.jsx";

// Phone setup (System Design 5.1): phones scan this once to learn the server addresses and the
// command post's public keys, so they can check alerts and seal reports. Nothing secret is in it.
export default function SetupQR({ onClose }) {
  const [setup, setSetup] = useState(null);
  const [error, setError] = useState(null);
  const [stamp] = useState(() => Date.now());

  useEffect(() => {
    get("/api/setup-qr").then(setSetup).catch((e) => setError(e.message));
  }, []);

  return (
    <Dialog title="Phone setup" onClose={onClose}>
      <div className="setup">
        <div className="qr-frame">
          <img src={`/api/setup-qr.png?t=${stamp}`} alt="Setup QR code for the PulseTriage phone app" />
        </div>
        <div>
          <p>Open the PulseTriage app on each phone and scan this code once, while the phone is near the command post.</p>
          {setup &&
          <>
              <p className="muted small-text">Server addresses in the code:</p>
              <ul className="small-text code-list">{setup.servers.map((s) => <li key={s}><code>{s}</code></li>)}</ul>
              <p className="muted small-text">
                {setup.zones.length} zones · alert key <code>{setup.sign_pk.slice(0, 10)}…</code>
              </p>
              <p className="muted small-text">If the laptop's address changes (new Wi-Fi), phones must scan again.</p>
            </>
          }
          {error && <p className="error" role="alert">{error}</p>}
        </div>
      </div>
    </Dialog>);

}
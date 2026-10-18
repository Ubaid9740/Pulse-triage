import { badgeTone } from "../format.js";
import Icon from "./Icon.jsx";

const TONE_ICON = { critical: "alert", success: "check", warning: "info", info: "fileText", override: "pencil" };

// One case badge (VERIFY, re-check, verified, override, "2 reports"…): text plus tone, never colour alone.
export default function Badge({ text }) {
  const tone = badgeTone(text);
  const icon = TONE_ICON[tone];
  return (
    <span className={`badge badge-${text.replace(/\s/g, "-")} tone-${tone}`}>
      {icon && <Icon name={icon} size={11} />}
      {text}
    </span>);

}
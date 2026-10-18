// Copy the hazard profiles from shared/ into the app, so the report form works before setup and
// with no connection. Run after changing shared/profiles: npm run profiles
import { readdirSync, readFileSync, writeFileSync } from "node:fs";

const from = new URL("../../shared/profiles/", import.meta.url);
const to = new URL("../src/profiles/", import.meta.url);
const names = readdirSync(from).filter((f) => f.endsWith(".json")).sort();
for (const f of names) writeFileSync(new URL(f, to), readFileSync(new URL(f, from)));
const hazards = names.filter((f) => f !== "common.json").map((f) => f.replace(".json", ""));
const lines = [
  "// Made by scripts/copy-profiles.mjs from shared/profiles. Do not edit; run npm run profiles.",
  'import common from "./common.json";',
  ...hazards.map((h) => `import ${h} from "./${h}.json";`),
  "",
  `export default { common, profiles: { ${hazards.join(", ")} } };`,
  "",
];
writeFileSync(new URL("index.js", to), lines.join("\n"));
console.log("copied", names.join(", "));

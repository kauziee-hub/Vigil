// Runs frontend/tests/v10.checks.tsx without a test framework: esbuild (already installed with Vite) bundles it for
// Node, then it executes. Usage from the repo root:  node scripts/frontend_checks.mjs
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join } from "node:path";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";

const root = fileURLToPath(new URL("..", import.meta.url));
const fe = join(root, "frontend");
const require = createRequire(join(fe, "package.json"));
const esbuild = require("esbuild");
const out = join(mkdtempSync(join(tmpdir(), "vigil-fe-")), "checks.mjs");
await esbuild.build({
  entryPoints: [join(fe, "tests", "v10.checks.tsx")], bundle: true, platform: "node", format: "esm", outfile: out,
  jsx: "automatic", logLevel: "error", nodePaths: [join(fe, "node_modules")],
  banner: { js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);" },
});
console.log("Vigil frontend checks (v10)");
await import(pathToFileURL(out).href);

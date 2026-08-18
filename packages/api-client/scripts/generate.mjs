#!/usr/bin/env node
// Regenerates the typed bindings in src/schema.ts from the service tier's
// OpenAPI schema. Run via `pnpm --filter api-client generate`.
//
// Schema source, in order of preference:
//   1. SERVICE_OPENAPI_URL — fetch from a running service (e.g. a dev
//      server's /openapi.json).
//   2. `uv run` against apps/service, importing the app and exporting its
//      schema directly (see scripts/export_openapi.py).

import { spawnSync } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const pkgRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const schemaPath = path.join(pkgRoot, "openapi.json");
const schemaUrl = process.env.SERVICE_OPENAPI_URL;

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", ...options });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} exited with ${result.status}`);
  }
}

async function fetchSchema(url) {
  console.log(`Fetching OpenAPI schema from ${url}`);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`GET ${url} -> ${response.status} ${response.statusText}`);
  }
  const body = (await response.text()).replace(/\s+$/, "");
  writeFileSync(schemaPath, `${body}\n`);
}

function exportSchemaFromService() {
  const serviceDir = path.resolve(pkgRoot, "..", "..", "apps", "service");
  const exportScript = path.join(pkgRoot, "scripts", "export_openapi.py");
  console.log("Exporting OpenAPI schema from the service app via `uv run`");

  if (existsSync(path.join(serviceDir, "pyproject.toml"))) {
    run("uv", ["run", "python", exportScript], { cwd: serviceDir });
    return;
  }

  // apps/service has no uv project yet (the workspace-scaffold feature
  // lands it separately) — run the export script in an ephemeral uv
  // environment with just the packages it needs.
  run(
    "uv",
    ["run", "--python", "3.12", "--with", "fastapi", "--with", "pydantic", "python", exportScript],
    { cwd: pkgRoot },
  );
}

async function main() {
  if (schemaUrl) {
    await fetchSchema(schemaUrl);
  } else {
    exportSchemaFromService();
  }

  console.log("Generating typed bindings with openapi-typescript");
  run("openapi-typescript", [schemaPath, "-o", path.join(pkgRoot, "src", "schema.ts")], {
    cwd: pkgRoot,
  });
  console.log("Wrote src/schema.ts");
}

main().catch((error) => {
  console.error(error.message ?? error);
  process.exit(1);
});

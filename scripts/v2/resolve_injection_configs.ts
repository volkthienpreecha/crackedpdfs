// Resolve injection configs for the v2 corpus builder.
//
// Reads a JSON array of partial regime combinations on stdin and writes the
// matching array of resolved InjectionConfig objects on stdout. The Python
// builder in tools/crackedpdfs-v2 calls this once per run, so the TypeScript
// resolver stays the single source of truth for family overrides.
import { resolveInjectionConfig } from "../../src/backend/services/processing/layers/02-watermarking/injection-config";

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks).toString("utf-8");
}

async function main(): Promise<void> {
  const combos: unknown = JSON.parse(await readStdin());
  if (!Array.isArray(combos)) {
    throw new Error("Expected a JSON array of regime combinations on stdin.");
  }
  process.stdout.write(JSON.stringify(combos.map((combo) => resolveInjectionConfig(combo))));
}

main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});

/**
 * Generates `generated/types.ts` (json-schema-to-typescript) and
 * `generated/python/autumn_sse_protocol/models.py` (datamodel-code-generator
 * via uvx) from `schema.json`.
 */
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const schema = resolve(root, "schema.json");
const generated = resolve(root, "generated");
const generatedPython = resolve(generated, "python", "autumn_sse_protocol");

const DATAMODEL_CODEGEN_PIN = "datamodel-code-generator==0.32.0";

mkdirSync(generated, { recursive: true });
mkdirSync(generatedPython, { recursive: true });

function run(cmd: string, args: readonly string[]): Promise<void> {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(cmd, args, { stdio: "inherit", cwd: root });
    child.on("error", rejectPromise);
    child.on("exit", (status) => {
      if (status === 0) resolvePromise();
      else rejectPromise(new Error(`${cmd} ${args.join(" ")} exited with status ${status}`));
    });
  });
}

async function main(): Promise<void> {
  await Promise.all([
    run("pnpm", [
      "exec",
      "json2ts",
      "--input",
      schema,
      "--output",
      resolve(generated, "types.ts"),
      "--unreachableDefinitions",
    ]),
    run("uvx", [
      "--from",
      DATAMODEL_CODEGEN_PIN,
      "datamodel-codegen",
      "--input",
      schema,
      "--input-file-type",
      "jsonschema",
      "--output",
      resolve(generatedPython, "models.py"),
      "--output-model-type",
      "pydantic_v2.BaseModel",
      "--target-python-version",
      "3.12",
      "--use-union-operator",
      "--use-standard-collections",
      "--use-schema-description",
      "--collapse-root-models",
      "--disable-timestamp",
    ]),
  ]);
  // biome-ignore lint/suspicious/noConsole: stdout is the script's user-facing contract.
  console.log("✓ generated TS and Python from schema.json");
}

main().catch((err: unknown) => {
  // biome-ignore lint/suspicious/noConsole: stderr is how a CLI surfaces failure.
  console.error(err);
  process.exit(1);
});

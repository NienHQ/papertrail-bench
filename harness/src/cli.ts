#!/usr/bin/env node
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import type { Adapter } from "./adapter.js";
import { loadTruthCorpus } from "./corpus.js";
import { OracleAdapter } from "./adapters/oracle.js";
import { RefuseAdapter } from "./adapters/refuse.js";
import { Bm25Adapter } from "./baselines/bm25.js";
import { HybridRrfAdapter } from "./baselines/hybrid-rrf.js";
import { NaiveVectorAdapter } from "./baselines/naive-vector.js";
import { reportToMarkdown } from "./report.js";
import { runAdapterWithTruth } from "./run.js";
import { SubprocessAdapter } from "./subprocess.js";

const USAGE = `Usage: papertrail-eval --corpus <dir> (--adapter <name|path> | --subprocess <cmd>) [--out report.json]

  --corpus      corpus directory (manifest.json, messages/, ground_truth/, questions.jsonl)
  --adapter     built-in adapter name ("oracle", "refuse", "bm25",
                "naive-vector", "hybrid-rrf") or a path to a JS
                module whose default export is an Adapter, or a factory
                function returning one
  --subprocess  shell command speaking the JSONL protocol (see PROTOCOL.md)
  --out         also write the full JSON report to this path
`;

function fail(message: string): never {
  process.stderr.write(`${message}\n\n${USAGE}`);
  process.exit(2);
}

function isAdapter(value: unknown): value is Adapter {
  if (typeof value !== "object" || value === null) return false;
  const obj = value as Record<string, unknown>;
  return (
    typeof obj["name"] === "string" &&
    typeof obj["ingest"] === "function" &&
    typeof obj["answer"] === "function"
  );
}

async function loadModuleAdapter(path: string): Promise<Adapter> {
  const url = pathToFileURL(resolve(path)).href;
  const mod = (await import(url)) as { default?: unknown };
  let candidate: unknown = mod.default;
  if (typeof candidate === "function") {
    candidate = (candidate as () => unknown)();
  }
  if (!isAdapter(candidate)) {
    fail(`module at ${path} does not default-export an Adapter`);
  }
  return candidate;
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      corpus: { type: "string" },
      adapter: { type: "string" },
      subprocess: { type: "string" },
      out: { type: "string" },
    },
  });

  const corpusDir = values.corpus;
  if (corpusDir === undefined) fail("--corpus is required");
  if (values.adapter === undefined && values.subprocess === undefined) {
    fail("one of --adapter or --subprocess is required");
  }
  if (values.adapter !== undefined && values.subprocess !== undefined) {
    fail("--adapter and --subprocess are mutually exclusive");
  }

  const truth = loadTruthCorpus(corpusDir);

  let adapter: Adapter;
  if (values.subprocess !== undefined) {
    adapter = new SubprocessAdapter(values.subprocess);
  } else if (values.adapter === "oracle") {
    adapter = new OracleAdapter(truth);
  } else if (values.adapter === "refuse") {
    adapter = new RefuseAdapter();
  } else if (values.adapter === "bm25") {
    adapter = new Bm25Adapter();
  } else if (values.adapter === "naive-vector") {
    adapter = new NaiveVectorAdapter();
  } else if (values.adapter === "hybrid-rrf") {
    adapter = new HybridRrfAdapter();
  } else {
    adapter = await loadModuleAdapter(values.adapter as string);
  }

  const report = await runAdapterWithTruth(adapter, truth);
  process.stdout.write(reportToMarkdown(report));
  if (values.out !== undefined) {
    writeFileSync(values.out, `${JSON.stringify(report, null, 2)}\n`);
    process.stderr.write(`report written to ${values.out}\n`);
  }
}

main().catch((err: unknown) => {
  process.stderr.write(`${err instanceof Error ? err.stack ?? err.message : String(err)}\n`);
  process.exit(1);
});

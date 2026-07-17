import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Report } from "../src/report.js";
import { Bm25Adapter } from "../src/baselines/bm25.js";
import { HybridRrfAdapter } from "../src/baselines/hybrid-rrf.js";
import { NaiveVectorAdapter } from "../src/baselines/naive-vector.js";
import { parseEml } from "../src/baselines/substrate.js";
import { RefuseAdapter } from "../src/adapters/refuse.js";
import { runAdapter } from "../src/run.js";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const FIXTURE = join(HERE, "fixtures", "corpus-h1");
const BASELINES_SRC = join(HERE, "..", "src", "baselines");

function category(report: Report, n: number): number {
  const c = report.categories.find((row) => row.category === n);
  expect(c, `category ${String(n)} present`).toBeDefined();
  return c?.accuracy ?? 0;
}

describe("internal baselines on corpus-h1", () => {
  it("all three run without error and produce a valid report shape", async () => {
    for (const adapter of [new Bm25Adapter(), new NaiveVectorAdapter(), new HybridRrfAdapter()]) {
      const report = await runAdapter(adapter, FIXTURE);
      expect(report.adapter).toBe(adapter.name);
      expect(report.harness).toBe("papertrail-harness v1");
      expect(report.questionCount).toBe(24);
      expect(report.categories.map((c) => c.category)).toEqual([1, 2, 3]);
      expect(report.notes).toEqual([]);
      for (const q of report.questions) {
        expect(q.error, q.questionId).toBeUndefined();
        expect(q.score).toBeGreaterThanOrEqual(0);
        expect(q.score).toBeLessThanOrEqual(1);
        expect(Array.isArray(q.citations)).toBe(true);
      }
    }
  });

  it("bm25 beats the refuse adapter on category 1 and clears the floor", async () => {
    const bm25 = await runAdapter(new Bm25Adapter(), FIXTURE);
    const refuse = await runAdapter(new RefuseAdapter(), FIXTURE);
    const bm25Cat1 = category(bm25, 1);
    // Floor, not a target: exact-id token matching should score far higher.
    expect(bm25Cat1).toBeGreaterThanOrEqual(0.5);
    expect(category(refuse, 1)).toBe(0);
    expect(bm25Cat1).toBeGreaterThan(category(refuse, 1));
  });

  it("rrf fusion does not catastrophically hurt category 1", async () => {
    const bm25 = await runAdapter(new Bm25Adapter(), FIXTURE);
    const hybrid = await runAdapter(new HybridRrfAdapter(), FIXTURE);
    expect(category(hybrid, 1)).toBeGreaterThanOrEqual(category(bm25, 1) - 0.25);
  });

  it("is deterministic: two bm25 runs produce byte-identical report JSON", async () => {
    const first = await runAdapter(new Bm25Adapter(), FIXTURE);
    const second = await runAdapter(new Bm25Adapter(), FIXTURE);
    expect(JSON.stringify(second, null, 2)).toBe(JSON.stringify(first, null, 2));
  });
});

describe("eml mini-parser", () => {
  it("parses a fixture message with an attachment", () => {
    const raw = readFileSync(join(FIXTURE, "messages", "MSG-000003.eml"), "utf8");
    const parsed = parseEml(raw);
    expect(parsed.messageId).toBe("MSG-000003");
    expect(parsed.subject).toBe("Lease agreement LEASE-2024-001");
    expect(parsed.body.length).toBeGreaterThan(0);
    expect(parsed.body).toContain("Monthly rent is $1,975.18");
    expect(parsed.attachments).toHaveLength(1);
    expect(parsed.attachments[0]?.filename).toBe("LEASE-2024-001.txt");
    expect(parsed.attachments[0]?.text).toContain("LEASE AGREEMENT LEASE-2024-001");
  });

  it("decodes quoted-printable soft line breaks in bodies", () => {
    const raw = readFileSync(join(FIXTURE, "messages", "MSG-000001.eml"), "utf8");
    const parsed = parseEml(raw);
    // The raw file wraps this name across a soft break ("Silver=\nton").
    expect(parsed.body).toContain("Silverton Trading");
  });

  it("decodes base64 text attachments", () => {
    const attachmentText = "INVOICE INV-2024-9999\nTotal: $12.34\n";
    const raw = [
      "From: a <a@x.example>",
      "To: b <b@x.example>",
      "Subject: base64 test",
      "Date: Mon, 01 Jan 2024 00:00:00 +0000",
      "Message-ID: <MSG-999999@x.example>",
      "MIME-Version: 1.0",
      'Content-Type: multipart/mixed; boundary="bb"',
      "",
      "--bb",
      'Content-Type: text/plain; charset="utf-8"',
      "Content-Transfer-Encoding: 7bit",
      "",
      "See attachment.",
      "--bb",
      'Content-Type: text/plain; charset="utf-8"',
      "Content-Transfer-Encoding: base64",
      'Content-Disposition: attachment; filename="INV-2024-9999.txt"',
      "",
      Buffer.from(attachmentText, "utf8").toString("base64"),
      "--bb--",
      "",
    ].join("\r\n");
    const parsed = parseEml(raw);
    expect(parsed.messageId).toBe("MSG-999999");
    expect(parsed.body).toBe("See attachment.");
    expect(parsed.attachments[0]?.text).toContain("Total: $12.34");
  });
});

describe("baselines never touch the answer key", () => {
  it("no source file under src/baselines imports truth loaders", () => {
    const files = readdirSync(BASELINES_SRC).filter((f) => f.endsWith(".ts"));
    expect(files.length).toBeGreaterThanOrEqual(5);
    for (const file of files) {
      const source = readFileSync(join(BASELINES_SRC, file), "utf8");
      expect(source, file).not.toMatch(/TruthCorpus|ground_truth/);
    }
  });
});

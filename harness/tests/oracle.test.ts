import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { OracleAdapter } from "../src/adapters/oracle.js";
import { RefuseAdapter } from "../src/adapters/refuse.js";
import { loadTruthCorpus } from "../src/corpus.js";
import { reportToMarkdown } from "../src/report.js";
import { runAdapterWithTruth } from "../src/run.js";

const FIXTURE = join(fileURLToPath(new URL(".", import.meta.url)), "fixtures", "corpus-h1");

describe("oracle self-test (the done criterion)", () => {
  it("scores 1.0 accuracy and citation precision = recall = 1.0 in every category", async () => {
    const truth = loadTruthCorpus(FIXTURE);
    const report = await runAdapterWithTruth(new OracleAdapter(truth), truth);

    expect(report.questionCount).toBe(truth.questions.length);
    expect(report.categories.length).toBeGreaterThan(0);
    for (const c of report.categories) {
      expect(c.accuracy, `category ${String(c.category)} accuracy`).toBe(1);
      expect(c.citationPrecision, `category ${String(c.category)} precision`).toBe(1);
      expect(c.citationRecall, `category ${String(c.category)} recall`).toBe(1);
    }
    expect(report.citationPrecision).toBe(1);
    expect(report.citationRecall).toBe(1);
    expect(report.notes).toEqual([]);
    for (const q of report.questions) {
      expect(q.score, q.questionId).toBe(1);
      expect(q.error).toBeUndefined();
    }
  });

  it("renders a markdown scorecard with per-category rows", async () => {
    const truth = loadTruthCorpus(FIXTURE);
    const report = await runAdapterWithTruth(new OracleAdapter(truth), truth);
    const md = reportToMarkdown(report);
    expect(md).toContain("| Category | N | Accuracy | Citation precision | Citation recall |");
    expect(md).toContain("| 1 |");
    expect(md).toContain("100.0");
    expect(md).not.toMatch(/overall accuracy/i);
  });

  it("is deterministic: two runs produce identical report JSON", async () => {
    const truth = loadTruthCorpus(FIXTURE);
    const first = await runAdapterWithTruth(new OracleAdapter(truth), truth);
    const second = await runAdapterWithTruth(new OracleAdapter(loadTruthCorpus(FIXTURE)), truth);
    expect(JSON.stringify(second, null, 2)).toBe(JSON.stringify(first, null, 2));
  });
});

describe("refuse adapter", () => {
  it("scores 0 accuracy on categories 1 to 3 with zero citation recall", async () => {
    const truth = loadTruthCorpus(FIXTURE);
    const report = await runAdapterWithTruth(new RefuseAdapter(), truth);

    for (const c of report.categories) {
      expect([1, 2, 3]).toContain(c.category);
      expect(c.accuracy, `category ${String(c.category)} accuracy`).toBe(0);
      expect(c.citationPrecision).toBeNull();
      expect(c.citationRecall).toBe(0);
    }
    expect(report.citationPrecision).toBeNull();
    expect(report.citationRecall).toBe(0);
  });
});

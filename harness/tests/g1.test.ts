/**
 * G1 acceptance: categories 4 (cross-thread dispute aggregation) and 6
 * (abstention) flow end to end through the harness.
 *
 * Fixture: tests/fixtures/corpus-g1, generated from the Python generator:
 *   cd generator && .venv/bin/python -m papertrail generate \
 *     --seed 19 --months 8 --vendors 4 --customers 2 \
 *     --out ../harness/tests/fixtures/corpus-g1
 * Default category_counts {1: 16, 2: 16, 3: 16, 4: 16, 6: 16}; this small
 * world yields questions {1: 16, 2: 16, 3: 8, 4: 12, 6: 16} over 620
 * messages, so every shipped category is populated.
 */
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { OracleAdapter } from "../src/adapters/oracle.js";
import { RefuseAdapter } from "../src/adapters/refuse.js";
import { loadTruthCorpus } from "../src/corpus.js";
import type { Report } from "../src/report.js";
import { runAdapterWithTruth } from "../src/run.js";

const FIXTURE = join(fileURLToPath(new URL(".", import.meta.url)), "fixtures", "corpus-g1");

function expectNoNaN(report: Report): void {
  for (const c of report.categories) {
    expect(Number.isNaN(c.accuracy), `category ${String(c.category)} accuracy`).toBe(false);
    if (c.citationPrecision !== null) {
      expect(Number.isNaN(c.citationPrecision)).toBe(false);
    }
    if (c.citationRecall !== null) {
      expect(Number.isNaN(c.citationRecall)).toBe(false);
    }
  }
  if (report.citationPrecision !== null) {
    expect(Number.isNaN(report.citationPrecision)).toBe(false);
  }
  if (report.citationRecall !== null) {
    expect(Number.isNaN(report.citationRecall)).toBe(false);
  }
}

describe("corpus-g1 fixture", () => {
  it("populates categories 1, 2, 3, 4 and 6", () => {
    const truth = loadTruthCorpus(FIXTURE);
    const cats = new Set(truth.questions.map((q) => q.category));
    expect([...cats].sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 6]);
    for (const cat of [1, 2, 3, 4, 6]) {
      expect(
        truth.questions.filter((q) => q.category === cat).length,
        `category ${String(cat)}`,
      ).toBeGreaterThan(0);
    }
  });

  it("gives category 6 questions an abstain answer and empty evidence", () => {
    const truth = loadTruthCorpus(FIXTURE);
    const q6 = truth.questions.filter((q) => q.category === 6);
    expect(q6.length).toBeGreaterThanOrEqual(15);
    for (const q of q6) {
      expect(q.answer.type).toBe("abstain");
      expect(q.answer.value).toBeNull();
      expect(q.evidence).toEqual([]);
    }
  });

  it("gives every category 4 question non-empty message-statement evidence", () => {
    const truth = loadTruthCorpus(FIXTURE);
    const q4 = truth.questions.filter((q) => q.category === 4);
    expect(q4.length).toBeGreaterThan(0);
    for (const q of q4) {
      expect(q.evidence.length).toBeGreaterThan(0);
      for (const ref of q.evidence) expect(ref).toHaveProperty("statement_id");
    }
  });
});

describe("oracle on corpus-g1", () => {
  it("scores 1.0 accuracy in every category, including abstention", async () => {
    const truth = loadTruthCorpus(FIXTURE);
    const report = await runAdapterWithTruth(new OracleAdapter(truth), truth);

    expect(report.questionCount).toBe(truth.questions.length);
    expect(report.categories.map((c) => c.category)).toEqual([1, 2, 3, 4, 6]);
    for (const c of report.categories) {
      expect(c.accuracy, `category ${String(c.category)} accuracy`).toBe(1);
      if (c.category === 6) {
        // no evidence and no predicted citations: metrics are null, not NaN
        expect(c.citationPrecision).toBeNull();
        expect(c.citationRecall).toBeNull();
      } else {
        expect(c.citationPrecision, `category ${String(c.category)} precision`).toBe(1);
        expect(c.citationRecall, `category ${String(c.category)} recall`).toBe(1);
      }
    }
    expect(report.citationPrecision).toBe(1);
    expect(report.citationRecall).toBe(1);
    expect(report.notes).toEqual([]);
    expectNoNaN(report);
  });
});

describe("refuse adapter on corpus-g1 (the H1 plan promise)", () => {
  it("scores 1.0 on category 6 and 0 everywhere else", async () => {
    const truth = loadTruthCorpus(FIXTURE);
    const report = await runAdapterWithTruth(new RefuseAdapter(), truth);

    for (const c of report.categories) {
      if (c.category === 6) {
        expect(c.accuracy, "abstention accuracy").toBe(1);
      } else {
        expect(c.accuracy, `category ${String(c.category)} accuracy`).toBe(0);
      }
    }
    expectNoNaN(report);
  });
});

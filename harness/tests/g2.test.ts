/**
 * G2 acceptance: category 5 (entity resolution) flows end to end through
 * the harness and demonstrably punishes address-as-identity retrieval.
 *
 * Fixture: tests/fixtures/corpus-g2, generated from the Python generator:
 *   cd generator && .venv/bin/python -m papertrail generate \
 *     --seed 23 --months 10 --vendors 5 --customers 2 \
 *     --out ../harness/tests/fixtures/corpus-g2
 * Default category_counts {1: 16, 2: 16, 3: 16, 4: 16, 5: 16, 6: 16};
 * this world yields questions {1: 16, 2: 16, 3: 10, 4: 15, 5: 16, 6: 16}
 * over 853 messages, with one PERSON_MOVED (2024-06-13, vendor to vendor,
 * leaving four months of post-move activity) and two CONTACT_CHANGED
 * events (one vendor contact, one customer contact).
 */
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { OracleAdapter } from "../src/adapters/oracle.js";
import { Bm25Adapter } from "../src/baselines/bm25.js";
import type { PersonRow } from "../src/corpus.js";
import { loadTruthCorpus } from "../src/corpus.js";
import type { Report } from "../src/report.js";
import { runAdapter, runAdapterWithTruth } from "../src/run.js";

const FIXTURE = join(fileURLToPath(new URL(".", import.meta.url)), "fixtures", "corpus-g2");

function category(report: Report, n: number): number {
  const c = report.categories.find((row) => row.category === n);
  expect(c, `category ${String(n)} present`).toBeDefined();
  return c?.accuracy ?? 0;
}

function addressDomains(p: PersonRow): Set<string> {
  return new Set(p.addresses.map((a) => a.address.split("@")[1] ?? ""));
}

describe("corpus-g2 fixture", () => {
  it("populates categories 1 through 6, with at least 15 category 5 questions", () => {
    const truth = loadTruthCorpus(FIXTURE);
    const cats = new Set(truth.questions.map((q) => q.category));
    expect([...cats].sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5, 6]);
    for (const cat of [1, 2, 3, 4, 5, 6]) {
      expect(
        truth.questions.filter((q) => q.category === cat).length,
        `category ${String(cat)}`,
      ).toBeGreaterThan(0);
    }
    expect(truth.questions.filter((q) => q.category === 5).length).toBeGreaterThanOrEqual(15);
  });

  it("anchors at least 4 category 5 questions on the person who moved companies", () => {
    const truth = loadTruthCorpus(FIXTURE);
    // the mover is the one person whose addresses span two domains
    const movers = truth.people.filter((p) => addressDomains(p).size > 1);
    expect(movers).toHaveLength(1);
    const mover = movers[0];
    const moverQuestions = truth.questions.filter(
      (q) => q.category === 5 && q.params["person_id"] === mover?.person_id,
    );
    expect(moverQuestions.length).toBeGreaterThanOrEqual(4);
    const templates = new Set(truth.questions.filter((q) => q.category === 5).map((q) => q.template));
    expect([...templates].sort()).toEqual([
      "person_address_at",
      "person_invoices_list",
      "person_po_count",
    ]);
  });

  it("gives every category 5 question non-empty message-statement evidence", () => {
    const truth = loadTruthCorpus(FIXTURE);
    for (const q of truth.questions.filter((x) => x.category === 5)) {
      expect(q.evidence.length, q.question_id).toBeGreaterThan(0);
      for (const ref of q.evidence) expect(ref).toHaveProperty("statement_id");
    }
  });
});

describe("oracle on corpus-g2", () => {
  it("scores 1.0 accuracy everywhere with perfect citations outside abstention", async () => {
    const truth = loadTruthCorpus(FIXTURE);
    const report = await runAdapterWithTruth(new OracleAdapter(truth), truth);

    expect(report.questionCount).toBe(truth.questions.length);
    expect(report.categories.map((c) => c.category)).toEqual([1, 2, 3, 4, 5, 6]);
    for (const c of report.categories) {
      expect(c.accuracy, `category ${String(c.category)} accuracy`).toBe(1);
      if (c.category === 6) {
        // abstention questions have empty evidence, so citation metrics
        // are null there rather than numbers
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
  });
});

describe("bm25 on corpus-g2 (the G2 done criterion)", () => {
  it("fails category 5 while holding its usual level on category 1", async () => {
    const report = await runAdapter(new Bm25Adapter(), FIXTURE);
    // The extract heuristics have no person-aggregation family: a system
    // that treats addresses as identities cannot follow a person across
    // addresses and employers. The gap is the point of the category.
    expect(category(report, 5)).toBeLessThan(0.5);
    expect(category(report, 1)).toBeGreaterThanOrEqual(0.5);
  }, 120_000);
});

/**
 * G3 acceptance: quoted-occurrence citation scoring and the canonical hit
 * rate, plus the done criterion: bm25 measurably degrades on a hard-preset
 * corpus versus the same-seed clean corpus.
 *
 * The clean side reuses the committed corpus-h1 fixture (seed 11, months 6,
 * vendors 3, customers 2, questions 24). The hard side regenerates the SAME
 * config with `--preset hard` into a temp directory; flags-off output is
 * byte-identical with the fixture, so the two runs differ only by the
 * realism screws.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { OracleAdapter } from "../src/adapters/oracle.js";
import { Bm25Adapter } from "../src/baselines/bm25.js";
import type { MessageRow, Question, StatementRow, TruthCorpus } from "../src/corpus.js";
import { loadTruthCorpus } from "../src/corpus.js";
import type { QuestionResult, Report } from "../src/report.js";
import { buildReport, reportToMarkdown } from "../src/report.js";
import { scoreCitations } from "../src/score.js";
import { runAdapter, runAdapterWithTruth } from "../src/run.js";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const FIXTURE = join(HERE, "fixtures", "corpus-h1");
const GENERATOR_PYTHON = join(HERE, "..", "..", "generator", ".venv", "bin", "python");

/* ------------------------------------------------------------------ */
/* Hand-built corpus: one canonical statement, one quoted copy          */
/* ------------------------------------------------------------------ */

function quotedTruth(): TruthCorpus {
  const canonical: StatementRow = {
    statement_id: "MSG-000012-S1",
    message_id: "MSG-000012",
    occurrence: "canonical",
    span: [0, 10],
    text: "the fact",
    targets: [{ fact: "FCT-000001" }],
  };
  const quoted: StatementRow = {
    statement_id: "MSG-000015-Q1",
    message_id: "MSG-000015",
    occurrence: "quoted",
    span: [40, 50],
    text: "the fact",
    targets: [{ fact: "FCT-000001" }],
  };
  const message = (id: string, statements: StatementRow[]): MessageRow => ({
    message_id: id,
    thread_id: "THR-0001",
    ts: "2024-01-02T09:00:00+00:00",
    subject: "s",
    from_address: "a@x.example",
    from_name: "A",
    from_person: "PER-0001",
    to: [],
    in_reply_to: null,
    references: [],
    attachments: [],
    body: "",
    statements,
  });
  return {
    corpusDir: "/nonexistent",
    manifest: { config: {}, counts: {}, files: {} },
    questions: [],
    messages: new Map([
      ["MSG-000012", message("MSG-000012", [canonical])],
      ["MSG-000015", message("MSG-000015", [quoted])],
    ]),
    statements: new Map([
      [canonical.statement_id, canonical],
      [quoted.statement_id, quoted],
    ]),
    documents: new Map(),
    facts: [],
    parties: [],
    people: [],
    threads: [],
  };
}

const QUESTION: Question = {
  question_id: "Q-G3",
  category: 1,
  template: "t",
  text: "?",
  answer: { type: "string", value: "x" },
  evidence: [{ message_id: "MSG-000012", statement_id: "MSG-000012-S1" }],
  params: {},
};

describe("scoreCitations with quoted occurrences", () => {
  const truth = quotedTruth();

  it("all-canonical citations: every hit is canonical", () => {
    const s = scoreCitations(QUESTION, ["MSG-000012"], truth);
    expect(s).toEqual({
      predicted: 1,
      hits: 1,
      canonicalHits: 1,
      evidenceTotal: 1,
      evidenceHit: 1,
    });
  });

  it("a message containing only a quoted copy hits but is not canonical", () => {
    const s = scoreCitations(QUESTION, ["MSG-000015"], truth);
    expect(s).toEqual({
      predicted: 1,
      hits: 1,
      canonicalHits: 0,
      evidenceTotal: 1,
      evidenceHit: 1,
    });
  });

  it("citing the quoted statement id directly hits but is not canonical", () => {
    const s = scoreCitations(QUESTION, ["MSG-000015-Q1"], truth);
    expect(s).toEqual({
      predicted: 1,
      hits: 1,
      canonicalHits: 0,
      evidenceTotal: 1,
      evidenceHit: 1,
    });
  });

  it("mixed citations: half the hits are canonical", () => {
    const s = scoreCitations(QUESTION, ["MSG-000012", "MSG-000015"], truth);
    expect(s).toEqual({
      predicted: 2,
      hits: 2,
      canonicalHits: 1,
      evidenceTotal: 1,
      evidenceHit: 1,
    });
  });

  it("a quoted copy with unrelated targets never hits", () => {
    const other: Question = {
      ...QUESTION,
      evidence: [{ message_id: "MSG-000012", statement_id: "MSG-000012-S1" }],
    };
    const t = quotedTruth();
    const q = t.statements.get("MSG-000015-Q1");
    if (q !== undefined) q.targets = [{ fact: "FCT-000999" }];
    const s = scoreCitations(other, ["MSG-000015"], t);
    expect(s.hits).toBe(0);
    expect(s.canonicalHits).toBe(0);
  });
});

describe("canonicalHitRate in the report", () => {
  function row(category: number, hits: number, canonicalHits: number): QuestionResult {
    return {
      questionId: `Q-${String(category)}`,
      category,
      template: "t",
      answerType: "string",
      score: 1,
      answer: "x",
      citations: [],
      citationPredicted: hits,
      citationHits: hits,
      citationCanonicalHits: canonicalHits,
      evidenceTotal: 2,
      evidenceHit: hits,
    };
  }

  it("is 100 for all-canonical, 0 for all-quoted, 50 for mixed, n/a for no hits", () => {
    const report = buildReport(
      "test",
      "/x",
      1,
      [row(1, 2, 2), row(2, 2, 0), row(3, 2, 1), row(4, 0, 0)],
      [],
    );
    const byCat = new Map(report.categories.map((c) => [c.category, c.canonicalHitRate]));
    expect(byCat.get(1)).toBe(1);
    expect(byCat.get(2)).toBe(0);
    expect(byCat.get(3)).toBe(0.5);
    expect(byCat.get(4)).toBeNull();
    expect(report.canonicalHitRate).toBe(0.5);

    const md = reportToMarkdown(report);
    expect(md).toContain("Canonical hit rate");
    expect(md).toContain("| 1 | 1 | 100.0 | 100.0 | 100.0 | 100.0 |");
    expect(md).toContain("| 2 | 1 | 100.0 | 100.0 | 100.0 | 0.0 |");
    expect(md).toContain("| 3 | 1 | 100.0 | 100.0 | 100.0 | 50.0 |");
    expect(md).toContain("| 4 | 1 | 100.0 | n/a | 0.0 | n/a |");
  });
});

describe("oracle on the clean fixture (no quoted occurrences)", () => {
  it("reports canonical hit rate 100.0 overall and per evidence-bearing category", async () => {
    const truth = loadTruthCorpus(FIXTURE);
    const report = await runAdapterWithTruth(new OracleAdapter(truth), truth);
    expect(report.canonicalHitRate).toBe(1);
    for (const c of report.categories) {
      if (c.category === 6) expect(c.canonicalHitRate).toBeNull();
      else expect(c.canonicalHitRate, `category ${String(c.category)}`).toBe(1);
    }
  });
});

/* ------------------------------------------------------------------ */
/* The G3 done criterion                                               */
/* ------------------------------------------------------------------ */

function category(report: Report, n: number): number {
  const c = report.categories.find((r) => r.category === n);
  expect(c, `category ${String(n)} present`).toBeDefined();
  return c?.accuracy ?? 0;
}

describe("bm25 degrades on the hard preset (the G3 done criterion)", () => {
  let hardDir = "";

  beforeAll(() => {
    expect(
      existsSync(GENERATOR_PYTHON),
      `generator venv missing at ${GENERATOR_PYTHON}; run its setup first`,
    ).toBe(true);
    hardDir = mkdtempSync(join(tmpdir(), "papertrail-hard-"));
    // same config as the committed corpus-h1 fixture, plus --preset hard
    execFileSync(GENERATOR_PYTHON, [
      "-m", "papertrail", "generate",
      "--seed", "11", "--months", "6", "--vendors", "3", "--customers", "2",
      "--questions", "24", "--preset", "hard", "--out", hardDir,
    ], { cwd: join(HERE, "..", "..", "generator"), stdio: "pipe" });
  });

  afterAll(() => {
    if (hardDir.length > 0) rmSync(hardDir, { recursive: true, force: true });
  });

  it("scores lower in at least one of categories 1 to 3, with canonical hit rate below 100", async () => {
    const evidence = readFileSync(join(hardDir, "ground_truth", "evidence.jsonl"), "utf8");
    const occurrences = new Set(
      evidence
        .split("\n")
        .filter((l) => l.trim().length > 0)
        .map((l) => (JSON.parse(l) as StatementRow).occurrence),
    );
    expect(occurrences).toContain("quoted");

    const clean = await runAdapter(new Bm25Adapter(), FIXTURE);
    const hard = await runAdapter(new Bm25Adapter(), hardDir);

    const degraded = [1, 2, 3].filter((n) => category(hard, n) < category(clean, n));
    expect(degraded.length, "no degradation in categories 1 to 3").toBeGreaterThan(0);

    expect(hard.canonicalHitRate).not.toBeNull();
    expect(hard.canonicalHitRate ?? 1).toBeLessThan(1);
    expect(clean.canonicalHitRate).toBe(1);
  }, 120_000);
});

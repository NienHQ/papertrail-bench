import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { loadTruthCorpus } from "../src/corpus.js";
import { runAdapterWithTruth } from "../src/run.js";
import { SubprocessAdapter } from "../src/subprocess.js";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const FIXTURE = join(HERE, "fixtures", "corpus-h1");
const ECHO = join(HERE, "fixtures", "echo-adapter.mjs");

describe("subprocess protocol round trip", () => {
  it("scores exactly what the child process answered", async () => {
    const truth = loadTruthCorpus(FIXTURE);
    const adapter = new SubprocessAdapter(`node ${ECHO}`, {
      name: "echo",
      questionTimeoutMs: 500,
    });
    const report = await runAdapterWithTruth(adapter, truth, {
      questionTimeoutMs: 5_000,
    });

    expect(report.adapter).toBe("echo");
    expect(report.questionCount).toBe(truth.questions.length);

    const byId = new Map(report.questions.map((q) => [q.questionId, q]));

    // Q-0001 was answered correctly with its exact evidence set.
    const q1 = byId.get("Q-0001");
    expect(q1?.score).toBe(1);
    expect(q1?.citationPredicted).toBe(2);
    expect(q1?.citationHits).toBe(2);
    expect(q1?.evidenceHit).toBe(q1?.evidenceTotal);
    expect(q1?.error).toBeUndefined();

    // Q-0002 emitted a non-JSON line: scored 0 and noted.
    const q2 = byId.get("Q-0002");
    expect(q2?.score).toBe(0);
    expect(q2?.error).toContain("bad JSON");
    expect(report.notes.some((n) => n.startsWith("Q-0002") && n.includes("bad JSON"))).toBe(true);

    // Q-0003 never replied: timed out, scored 0 and noted.
    const q3 = byId.get("Q-0003");
    expect(q3?.score).toBe(0);
    expect(q3?.error).toContain("timeout");
    expect(report.notes.some((n) => n.startsWith("Q-0003") && n.includes("timeout"))).toBe(true);

    // Everything else got garbage with an unresolvable citation.
    for (const q of report.questions) {
      if (["Q-0001", "Q-0002", "Q-0003"].includes(q.questionId)) continue;
      expect(q.score, q.questionId).toBe(0);
      expect(q.citationPredicted, q.questionId).toBe(1);
      expect(q.citationHits, q.questionId).toBe(0);
      expect(q.evidenceHit, q.questionId).toBe(0);
    }

    // Aggregates reflect exactly one correct answer, in Q-0001's category.
    const q1Category = truth.questions.find((q) => q.question_id === "Q-0001")?.category;
    for (const c of report.categories) {
      const n = truth.questions.filter((q) => q.category === c.category).length;
      expect(c.n).toBe(n);
      expect(c.accuracy).toBeCloseTo(c.category === q1Category ? 1 / n : 0);
    }
  }, 60_000);
});

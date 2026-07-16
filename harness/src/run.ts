import type { Adapter } from "./adapter.js";
import type { TruthCorpus } from "./corpus.js";
import { loadSystemCorpus, loadTruthCorpus } from "./corpus.js";
import type { QuestionResult, Report } from "./report.js";
import { buildReport } from "./report.js";
import { scoreAnswer, scoreCitations } from "./score.js";

export const DEFAULT_INGEST_TIMEOUT_MS = 600_000;
export const DEFAULT_QUESTION_TIMEOUT_MS = 60_000;

export interface RunOptions {
  ingestTimeoutMs?: number;
  questionTimeoutMs?: number;
}

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`timeout after ${String(ms)} ms (${label})`));
    }, ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err: unknown) => {
        clearTimeout(timer);
        reject(err instanceof Error ? err : new Error(String(err)));
      },
    );
  });
}

export async function runAdapter(
  adapter: Adapter,
  corpusDir: string,
  options: RunOptions = {},
): Promise<Report> {
  const truth = loadTruthCorpus(corpusDir);
  return runAdapterWithTruth(adapter, truth, options);
}

/**
 * Run an adapter over a corpus and score every question. The adapter only
 * ever sees the SystemCorpus; the TruthCorpus stays on the runner's side.
 * A timed-out or failed question scores 0 and is listed in report notes.
 */
export async function runAdapterWithTruth(
  adapter: Adapter,
  truth: TruthCorpus,
  options: RunOptions = {},
): Promise<Report> {
  const ingestTimeoutMs = options.ingestTimeoutMs ?? DEFAULT_INGEST_TIMEOUT_MS;
  const questionTimeoutMs = options.questionTimeoutMs ?? DEFAULT_QUESTION_TIMEOUT_MS;
  const system = loadSystemCorpus(truth.corpusDir);
  const notes: string[] = [];
  const results: QuestionResult[] = [];

  try {
    await withTimeout(adapter.ingest(system), ingestTimeoutMs, "ingest");

    for (const q of truth.questions) {
      let answer: unknown = null;
      let citations: string[] = [];
      let error: string | undefined;
      try {
        const res = await withTimeout(
          adapter.answer({ id: q.question_id, category: q.category, text: q.text }),
          questionTimeoutMs,
          q.question_id,
        );
        answer = res.answer;
        citations = Array.isArray(res.citations)
          ? res.citations.filter((c): c is string => typeof c === "string")
          : [];
      } catch (err) {
        error = err instanceof Error ? err.message : String(err);
        notes.push(`${q.question_id} scored 0: ${error}`);
      }

      const score = error === undefined ? scoreAnswer(q.answer, answer) : 0;
      const cites =
        error === undefined
          ? scoreCitations(q, citations, truth)
          : { predicted: 0, hits: 0, evidenceTotal: q.evidence.length, evidenceHit: 0 };

      const result: QuestionResult = {
        questionId: q.question_id,
        category: q.category,
        template: q.template,
        answerType: q.answer.type,
        score,
        answer,
        citations,
        citationPredicted: cites.predicted,
        citationHits: cites.hits,
        evidenceTotal: cites.evidenceTotal,
        evidenceHit: cites.evidenceHit,
      };
      if (error !== undefined) result.error = error;
      results.push(result);
    }
  } finally {
    if (adapter.close !== undefined) {
      try {
        await adapter.close();
      } catch {
        // a failing close must not mask scores already collected
      }
    }
  }

  const seed = truth.manifest.config["seed"] ?? null;
  return buildReport(adapter.name, truth.corpusDir, seed, results, notes);
}

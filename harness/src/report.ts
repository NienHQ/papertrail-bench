export interface QuestionResult {
  questionId: string;
  category: number;
  template: string;
  answerType: string;
  score: number;
  answer: unknown;
  citations: string[];
  citationPredicted: number;
  citationHits: number;
  evidenceTotal: number;
  evidenceHit: number;
  error?: string;
}

export interface CategoryScore {
  category: number;
  n: number;
  /** Mean per-question answer score in [0, 1]. */
  accuracy: number;
  /** Micro-averaged; null when the adapter predicted no citations. */
  citationPrecision: number | null;
  /** Micro-averaged; null when the category has no evidence items. */
  citationRecall: number | null;
}

/**
 * The scorecard. Deliberately has no single blended number: per-category
 * accuracy plus citation precision and recall are the whole story.
 */
export interface Report {
  harness: string;
  adapter: string;
  corpusDir: string;
  seed: unknown;
  questionCount: number;
  categories: CategoryScore[];
  citationPrecision: number | null;
  citationRecall: number | null;
  notes: string[];
  questions: QuestionResult[];
}

function ratio(numerator: number, denominator: number): number | null {
  return denominator === 0 ? null : numerator / denominator;
}

export function buildReport(
  adapterName: string,
  corpusDir: string,
  seed: unknown,
  results: QuestionResult[],
  notes: string[],
): Report {
  const byCategory = new Map<number, QuestionResult[]>();
  for (const r of results) {
    const bucket = byCategory.get(r.category);
    if (bucket === undefined) byCategory.set(r.category, [r]);
    else bucket.push(r);
  }

  const categories: CategoryScore[] = [];
  for (const category of [...byCategory.keys()].sort((a, b) => a - b)) {
    const rows = byCategory.get(category) ?? [];
    const n = rows.length;
    const accuracy = n === 0 ? 0 : rows.reduce((s, r) => s + r.score, 0) / n;
    const predicted = rows.reduce((s, r) => s + r.citationPredicted, 0);
    const hits = rows.reduce((s, r) => s + r.citationHits, 0);
    const evidenceTotal = rows.reduce((s, r) => s + r.evidenceTotal, 0);
    const evidenceHit = rows.reduce((s, r) => s + r.evidenceHit, 0);
    categories.push({
      category,
      n,
      accuracy,
      citationPrecision: ratio(hits, predicted),
      citationRecall: ratio(evidenceHit, evidenceTotal),
    });
  }

  const predicted = results.reduce((s, r) => s + r.citationPredicted, 0);
  const hits = results.reduce((s, r) => s + r.citationHits, 0);
  const evidenceTotal = results.reduce((s, r) => s + r.evidenceTotal, 0);
  const evidenceHit = results.reduce((s, r) => s + r.evidenceHit, 0);

  return {
    harness: "papertrail-harness v1",
    adapter: adapterName,
    corpusDir,
    seed,
    questionCount: results.length,
    categories,
    citationPrecision: ratio(hits, predicted),
    citationRecall: ratio(evidenceHit, evidenceTotal),
    notes,
    questions: results,
  };
}

function pct(value: number | null): string {
  return value === null ? "n/a" : (value * 100).toFixed(1);
}

export function reportToMarkdown(report: Report): string {
  const lines: string[] = [];
  lines.push("# PaperTrail scorecard");
  lines.push("");
  lines.push(`Adapter: ${report.adapter}`);
  lines.push(`Corpus: ${report.corpusDir} (seed ${String(report.seed)})`);
  lines.push(`Questions: ${String(report.questionCount)}`);
  lines.push("");
  lines.push("| Category | N | Accuracy | Citation precision | Citation recall |");
  lines.push("|---:|---:|---:|---:|---:|");
  for (const c of report.categories) {
    lines.push(
      `| ${String(c.category)} | ${String(c.n)} | ${pct(c.accuracy)} | ` +
        `${pct(c.citationPrecision)} | ${pct(c.citationRecall)} |`,
    );
  }
  lines.push(
    `| all (citations) | ${String(report.questionCount)} |  | ` +
      `${pct(report.citationPrecision)} | ${pct(report.citationRecall)} |`,
  );
  if (report.notes.length > 0) {
    lines.push("");
    lines.push("Notes:");
    for (const note of report.notes) lines.push(`- ${note}`);
  }
  lines.push("");
  return lines.join("\n");
}

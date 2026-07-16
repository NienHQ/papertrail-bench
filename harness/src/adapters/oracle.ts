import type { Adapter, AdapterAnswer, AdapterQuestion } from "../adapter.js";
import type { EvidenceRef, Question, SystemCorpus, TruthCorpus } from "../corpus.js";
import { isMessageEvidenceRef } from "../corpus.js";

function refToCitation(ref: EvidenceRef): string {
  return isMessageEvidenceRef(ref) ? `${ref.message_id}:${ref.statement_id}` : ref.doc_id;
}

/**
 * The self-test adapter. It is the ONE adapter allowed to read the
 * TruthCorpus, handed to it by the runner at construction time, never via
 * the SystemCorpus. It answers every question straight from ground truth
 * and cites the full evidence set, so it must score 1.0 accuracy and
 * citation precision = recall = 1.0 on every category.
 */
export class OracleAdapter implements Adapter {
  readonly name = "oracle";
  private readonly byId = new Map<string, Question>();

  constructor(truth: TruthCorpus) {
    for (const q of truth.questions) this.byId.set(q.question_id, q);
  }

  async ingest(_corpus: SystemCorpus): Promise<void> {
    // Ground truth was injected at construction; nothing to ingest.
  }

  async answer(q: AdapterQuestion): Promise<AdapterAnswer> {
    const question = this.byId.get(q.id);
    if (question === undefined) return { answer: null, citations: [] };
    const citations = [...new Set(question.evidence.map(refToCitation))];
    return { answer: question.answer.value, citations };
  }
}

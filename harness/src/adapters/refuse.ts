import type { Adapter, AdapterAnswer, AdapterQuestion } from "../adapter.js";
import type { SystemCorpus } from "../corpus.js";

/**
 * Answers null with no citations to every question. Scores 0 everywhere
 * except the abstention category (category 6, once corpora include it),
 * where refusing is the correct answer.
 */
export class RefuseAdapter implements Adapter {
  readonly name = "refuse";

  async ingest(_corpus: SystemCorpus): Promise<void> {
    // Nothing to ingest.
  }

  async answer(_q: AdapterQuestion): Promise<AdapterAnswer> {
    return { answer: null, citations: [] };
  }
}

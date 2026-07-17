import type { Adapter, AdapterAnswer, AdapterQuestion } from "../adapter.js";
import type { SystemCorpus } from "../corpus.js";
import { BASELINE_TOP_K } from "./bm25.js";
import { extractAnswer } from "./extract.js";
import { loadChunks, VectorIndex } from "./substrate.js";

/**
 * Vector-store stand-in: a deterministic fnv1a bag-of-words hash embedder
 * (64 dims, L2 normalized) with cosine top-k, then the same extraction as
 * bm25. No model and no network, so runs reproduce byte for byte; numbers
 * for real embedding models require an API and are out of scope here.
 */
export class NaiveVectorAdapter implements Adapter {
  readonly name: string = "naive-vector";
  private index: VectorIndex | null = null;

  async ingest(corpus: SystemCorpus): Promise<void> {
    this.index = new VectorIndex(loadChunks(corpus));
  }

  async answer(q: AdapterQuestion): Promise<AdapterAnswer> {
    if (this.index === null) return { answer: null, citations: [] };
    return extractAnswer(q.text, this.index.search(q.text, BASELINE_TOP_K).map((r) => r.chunk));
  }
}

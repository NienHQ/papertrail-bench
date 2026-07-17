import type { Adapter, AdapterAnswer, AdapterQuestion } from "../adapter.js";
import type { SystemCorpus } from "../corpus.js";
import { BASELINE_TOP_K } from "./bm25.js";
import { extractAnswer } from "./extract.js";
import { Bm25Index, loadChunks, rrfFuse, VectorIndex } from "./substrate.js";

/**
 * Hybrid baseline: the bm25 and naive-vector candidate lists fused with
 * reciprocal rank fusion (k=60), then the shared extraction.
 */
export class HybridRrfAdapter implements Adapter {
  readonly name: string = "hybrid-rrf";
  private bm25: Bm25Index | null = null;
  private vectors: VectorIndex | null = null;

  async ingest(corpus: SystemCorpus): Promise<void> {
    const chunks = loadChunks(corpus);
    this.bm25 = new Bm25Index(chunks);
    this.vectors = new VectorIndex(chunks);
  }

  async answer(q: AdapterQuestion): Promise<AdapterAnswer> {
    if (this.bm25 === null || this.vectors === null) return { answer: null, citations: [] };
    const fused = rrfFuse(
      [this.bm25.search(q.text, BASELINE_TOP_K), this.vectors.search(q.text, BASELINE_TOP_K)],
      BASELINE_TOP_K,
    );
    return extractAnswer(q.text, fused.map((r) => r.chunk));
  }

  async close(): Promise<void> {
    this.bm25?.close();
    this.bm25 = null;
    this.vectors = null;
  }
}

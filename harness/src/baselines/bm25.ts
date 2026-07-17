import type { Adapter, AdapterAnswer, AdapterQuestion } from "../adapter.js";
import type { SystemCorpus } from "../corpus.js";
import { extractAnswer } from "./extract.js";
import { Bm25Index, loadChunks } from "./substrate.js";

export const BASELINE_TOP_K = 10;

/**
 * Lexical baseline: sqlite FTS5 (porter tokenizer) over message-body and
 * attachment chunks, query = OR of question tokens, bm25 ranking, then
 * template-family extraction over the top hits.
 */
export class Bm25Adapter implements Adapter {
  readonly name: string = "bm25";
  private index: Bm25Index | null = null;

  async ingest(corpus: SystemCorpus): Promise<void> {
    this.index = new Bm25Index(loadChunks(corpus));
  }

  async answer(q: AdapterQuestion): Promise<AdapterAnswer> {
    if (this.index === null) return { answer: null, citations: [] };
    return extractAnswer(q.text, this.index.search(q.text, BASELINE_TOP_K).map((r) => r.chunk));
  }

  async close(): Promise<void> {
    this.index?.close();
    this.index = null;
  }
}

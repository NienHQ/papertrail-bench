import type { SystemCorpus } from "./corpus.js";

export interface AdapterQuestion {
  id: string;
  category: number;
  text: string;
}

export interface AdapterAnswer {
  answer: unknown;
  citations: string[];
}

/**
 * A system under test. The runner calls ingest once with the SystemCorpus
 * (messages and attachments only), then answer once per question, then
 * close if defined.
 *
 * Citations are strings resolvable against ground truth. Accepted forms:
 *   - bare message id:            "MSG-000012"
 *   - message id with domain:     "MSG-000012@x.example"
 *   - message id + statement id:  "MSG-000012:MSG-000012-S1"
 *   - bare statement id:          "MSG-000012-S1"
 *   - doc id:                     "INV-2024-0007"
 * See PROTOCOL.md for the exact resolution and scoring rules.
 */
export interface Adapter {
  name: string;
  ingest(corpus: SystemCorpus): Promise<void>;
  answer(q: AdapterQuestion): Promise<AdapterAnswer>;
  close?(): Promise<void>;
}

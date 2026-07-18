# Internal baselines: scorecards

Milestone H2, refreshed after G2 (six categories live; earlier revisions
of this file predate categories 4 to 6). Three reference systems live in
`harness/src/baselines/` and are registered as built-in adapters in the
harness CLI:

- `bm25`: sqlite FTS5 (porter tokenizer) over message-body and attachment
  chunks; the query is an OR of stopword-filtered question tokens; answers
  come from template-family extraction heuristics over the top 10 chunks.
- `naive-vector`: a deterministic hash embedder (fnv1a bag-of-words folded
  into 64 dims, L2 normalized) with cosine top-k and the same extraction.
  No model and no network, so every run reproduces byte for byte. This is
  a floor for "a vector store", not an estimate of real embedding models;
  real-model numbers require an API and are out of scope here.
- `hybrid-rrf`: the bm25 and naive-vector candidate lists fused with
  reciprocal rank fusion (k=60), same extraction.

All three ingest only `messages/` and `attachments/` (the SystemCorpus).
They never read ground truth; a test greps their sources to prove it.
`oracle` (answers straight from ground truth) brackets the table from
above; a refuse-everything system would score 100 on category 6 and 0
everywhere else.

## Fixture corpus-h1 (seed 11, 323 messages, 21 questions)

Reproduce:

```sh
cd generator && .venv/bin/python -m papertrail generate --seed 11 --months 6 \
  --vendors 3 --customers 2 --questions 24 --out /tmp/corpus-h1
cd ../harness && pnpm build && node dist/cli.js --corpus /tmp/corpus-h1 --adapter bm25
```

| Adapter | Cat 1 | Cat 2 | Cat 3 | Cat 4 | Cat 5 | Cat 6 | Cit. P | Cit. R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| bm25 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 100.0 | 58.8 | 27.8 |
| naive-vector | 50.0 | 62.5 | 100.0 | 0.0 | 0.0 | 100.0 | 52.0 | 18.1 |
| hybrid-rrf | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 100.0 | 71.9 | 31.9 |

## Default corpus (seed 42, 1672 messages, 96 questions)

Reproduce:

```sh
cd generator && .venv/bin/python -m papertrail generate --seed 42 --out /tmp/corpus-b0
cd ../harness && pnpm build && node dist/cli.js --corpus /tmp/corpus-b0 --adapter bm25
```

| Adapter | Cat 1 | Cat 2 | Cat 3 | Cat 4 | Cat 5 | Cat 6 | Cit. P | Cit. R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| bm25 | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 100.0 | 59.3 | 15.3 |
| naive-vector | 6.3 | 31.3 | 81.3 | 0.0 | 0.0 | 100.0 | 27.5 | 5.1 |
| hybrid-rrf | 100.0 | 100.0 | 100.0 | 0.0 | 0.0 | 100.0 | 65.2 | 15.8 |

## Reading the table

- Categories 1 to 3 saturate for keyword systems: document ids are
  exact-match tokens, so bm25 (and hybrid, which contains it) answer
  everything. That was the B0 state of the bench and is why categories
  4 to 6 exist.
- Category 4 (cross-thread aggregation) and category 5 (entity
  resolution across addresses and employers) drop every baseline to
  zero: no single chunk contains the answer, and address-as-identity
  retrieval cannot follow a person across domains. These are the
  categories that separate engines from search boxes.
- The baselines' 100 on category 6 (abstention) is partly accidental:
  they refuse whenever no extraction family matches, which happens to be
  correct for never-issued ids. Score abstention together with the other
  categories or it rewards timidity.
- bm25 beats naive-vector on category 1 on both corpora (100 vs 50 and
  100 vs 6.3): exact identifiers drown in a weak hash embedding space.
  Fusion recovers bm25's accuracy and improves citation precision.
- Citation precision and recall stay well under oracle for every
  baseline even where accuracy is 100: finding the right answer is not
  the same as citing all of its evidence.

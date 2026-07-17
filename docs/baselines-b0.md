# Internal baselines: B0 scorecards

Milestone H2. Three reference systems live in `harness/src/baselines/` and
are registered as built-in adapters in the harness CLI:

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
`oracle` (answers straight from ground truth) and `refuse` (answers null to
everything) bracket the table from above and below.

Accuracy is per category (mean per-question score). Citation precision and
recall are micro-averaged over all questions: precision is the share of
predicted citations that hit the question's evidence set, recall is the
share of evidence items covered by at least one predicted citation. The
harness reports both per category; the tables below show category accuracy
plus the overall citation columns.

## Committed fixture: harness/tests/fixtures/corpus-h1

Seed 11, 295 messages, 24 questions (categories 1 to 3: n = 12, 8, 4).

| Adapter | Cat 1 acc | Cat 2 acc | Cat 3 acc | Citation P | Citation R |
|---|---:|---:|---:|---:|---:|
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| refuse | 0.0 | 0.0 | 0.0 | n/a | 0.0 |
| bm25 | 100.0 | 100.0 | 100.0 | 85.4 | 74.5 |
| naive-vector | 25.0 | 75.0 | 100.0 | 64.5 | 42.6 |
| hybrid-rrf | 100.0 | 100.0 | 100.0 | 100.0 | 74.5 |

Reproduction (the corpus is committed; the first command regenerates the
identical fixture from its manifest config):

```
cd generator && .venv/bin/python -m papertrail generate --seed 11 --months 6 \
  --vendors 3 --customers 2 --questions 24 --out ../harness/tests/fixtures/corpus-h1
cd harness && pnpm build && node dist/cli.js \
  --corpus tests/fixtures/corpus-h1 --adapter bm25
```

## Regenerated default corpus (seed 42, not committed)

Default config: 1712 messages, 50 questions (n = 18, 16, 16).

| Adapter | Cat 1 acc | Cat 2 acc | Cat 3 acc | Citation P | Citation R |
|---|---:|---:|---:|---:|---:|
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| refuse | 0.0 | 0.0 | 0.0 | n/a | 0.0 |
| bm25 | 100.0 | 100.0 | 100.0 | 87.9 | 81.6 |
| naive-vector | 0.0 | 9.4 | 75.0 | 29.4 | 15.3 |
| hybrid-rrf | 100.0 | 100.0 | 93.8 | 98.8 | 80.6 |

Reproduction:

```
cd generator && .venv/bin/python -m papertrail generate --seed 42 --out /tmp/corpus-b0
cd harness && pnpm build && node dist/cli.js --corpus /tmp/corpus-b0 --adapter bm25
```

Swap `--adapter` for `oracle`, `refuse`, `naive-vector`, or `hybrid-rrf`
for the other rows; add `--out report.json` for the full per-question JSON.

## Analysis

bm25 beats naive-vector on category 1, as the plan expected: 100.0 vs 25.0
on the fixture and 100.0 vs 0.0 on the default corpus. Document ids like
INV-2024-0074 are exact-match tokens, and FTS5 keeps them discriminative
(the quoted id becomes a phrase query that only the right invoice message
and its attachment satisfy). The 64-dim hash embedder destroys exactly that
signal: every id collapses into a handful of collision-prone dimensions, so
cosine ranking cannot tell one invoice number from another, and the gap
widens on the larger corpus (18x more invoices competing for the same 64
dims). naive-vector stays respectable only on category 3, where the
question shares many ordinary words (vendor name, "payment terms") with the
right statements. hybrid-rrf tracks bm25 almost everywhere and repairs most
of bm25's citation precision losses (spurious amendment-chunk citations get
fused out of the top ranks), at the cost of one category 3 miss on the
default corpus where fusion pushed the deciding statement out of the top
10.

Two things to read off the citation columns: the refusal row shows the
floor behavior (null answers, no citations, so precision is undefined and
recall is 0, and every accuracy is 0 until an abstention category exists);
and the baselines' category 1 citation recall sits near 50 percent by
construction, because they cite only the message a value was parsed from
while the evidence set also contains the attachment's doc field. Answer
accuracy and citation quality really are separate axes, which is the point
of reporting them separately.

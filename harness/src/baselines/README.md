# Internal baselines

Reference systems the bench runs against itself: `bm25` (sqlite FTS5),
`naive-vector` (deterministic hash embedder), `hybrid-rrf` (both lists,
reciprocal rank fusion). All three share one ingest (`substrate.ts`: minimal
RFC822 parsing, chunking, indexes) and one answer extractor (`extract.ts`:
template-family heuristics keyed off the question text). Scorecards and
reproduction commands live in `docs/baselines-b0.md` at the repo root.

Two rules keep these honest:

- They see only the `SystemCorpus` (messages/ + attachments/). Nothing in
  this directory reads the answer key; a test greps these sources to prove
  it.
- They are dev-side. `better-sqlite3` and its types are devDependencies on
  purpose: the harness package is private and never published, so the
  native module is a cost only for people working inside this repo.

The hash embedder is a floor, not an estimate of real embedding models.
Real-model numbers require an API (nondeterministic, networked) and are out
of scope for the committed baselines.

# Status

Read this first when resuming work.

## 2026-07-15 — B0 core built

- `docs/ground-truth-schema.md` written — the load-bearing design doc. Change it
  first, code second.
- `generator/` (Python, stdlib-only, `papertrail` package) implements the full B0
  pipeline: seed → world → event log → {document chains, fact ledger} → rendered
  .eml corpus with per-statement char spans → questions (categories 1–3) with
  evidence sets. 14 invariant tests pass, including byte-determinism and
  EML span roundtrip.
- Default config (`--seed 42`): 1414 events, 918 documents, 31 facts, 497 threads,
  1712 messages, 50 questions.

## Next (toward B1)

- Realism screws: truncated References, quoted-reply duplication (`occurrence:
  quoted`), address/company changes, near-duplicate invoices, rasterized PDFs
  (Typst).
- Categories 4–7: disputes/aggregation, entity resolution, abstention, citation
  fidelity scoring.
- Typst PDF attachments alongside text/plain.
- 3-year corpus (`year` handling currently single-year; numbering assumes one
  year per series).
- TypeScript harness + internal baselines (BM25/FTS5, naive vector, hybrid+RRF,
  long-context).

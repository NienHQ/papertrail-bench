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

Superseded by [plan-b1.md](plan-b1.md): harness first (H1, H2), then
taxonomy and realism (G1 to G4), then convergence with Track 2.
Claim tasks here per the plan.

## In progress

- G3 realism screws (claimed 2026-07-18)

## 2026-07-18 - task G2 done: category 5 entity resolution

- Person model gains employment periods; CONTACT_CHANGED (same person,
  new address, announced once) and PERSON_MOVED (person changes vendor,
  farewell from the old address, replacement hired, new domain just
  starts appearing). All renderer scripts are date-aware senders now.
- Category 5 questions (PO count / invoice list / address-at across a
  person, independent recomputes, name-uniqueness guard). Default
  category_counts now 16 x 6 = 96 questions.
- Fixtures regenerated (new events shift the rng stream): corpus-h1 and
  corpus-g1 rebuilt with recorded flags, consumers updated; new
  corpus-g2 fixture (853 messages, 89 questions, one person move).
- Done criterion: oracle 100 on category 5; bm25 scores 0.0 there while
  holding 100 on category 1. Baselines doc refreshed: every baseline is
  at 0 on categories 4 and 5 on both corpora; the bench now separates
  engines from search boxes. Generator 22 tests, harness 70 tests.

## 2026-07-18 - task G1 done: categories 4 and 6

- Disputes: INVOICE_DISPUTED / DISPUTE_RESOLVED on vendor invoices
  (dispute_prob 0.12), credit_note resolutions reuse the existing CN
  machinery for exactly the disputed amount, withdrawn changes nothing;
  rendered as replies on the invoice thread. Dispute-consistency
  invariant test added.
- Questions: category 4 (disputed total/count/list per vendor, evidence
  = every contributing dispute statement) and category 6 (abstention:
  ids continuing real series past issuance, names from unused stems,
  structural-absence asserts, empty evidence). category_counts config
  (default 16 each for 1,2,3,4,6); n_questions deprecated even-split.
- Default seed-42 corpus: 16 questions per category, 1672 messages.
  New fixture harness/tests/fixtures/corpus-g1 (620 messages, 68
  questions, all 5 categories); harness g1 tests close the H1 promise:
  oracle 100 everywhere including abstention, refuse 100 on category 6
  only, no NaN citation metrics on empty evidence. Generator 19 tests,
  harness 65 tests.

## 2026-07-18 - task H3 done: protocol freeze + Docket ablations landed

- papertrail-protocol v1 frozen and tagged (harness-protocol-v1).
- The first external consumer exists: Docket (github.com/NienHQ/docket)
  ships a protocol-v1 adapter and committed ablation tables
  (docket docs/ablations.md). Its results confirm the bench needs the
  G milestone: categories 1 to 3 saturate for competent systems; the
  differentiating axis today is citation precision/recall.
  Next: G1 (categories 4 and 6).

## 2026-07-17 - task H2 done: internal baselines

- bm25 (FTS5 + stopword-filtered OR queries), naive-vector (64-dim hash
  embedder), hybrid-rrf, all behind the same no-ground-truth wall
  (enforced by a source-scan test). Question-text template extraction,
  citations from the parsed chunks. 60 harness tests.
- docs/baselines-b0.md: scorecards on the fixture and the seed-42
  corpus. Headline: bm25 100/100/100 vs naive-vector 25/75/100 (fixture)
  and 0/9/75 (seed-42) because exact-match ids drown in a hash embedder;
  hybrid-rrf recovers bm25 accuracy with better citation precision.
  Reproduction commands committed. Next: H3 protocol freeze + Docket
  adapter/ablations (Docket repo task 3.3).

## 2026-07-17 - task H1 done: harness core + oracle self-test

- harness/ (TypeScript, zero runtime deps): SystemCorpus/TruthCorpus wall,
  Adapter interface, deterministic scorers for every answer type, citation
  precision/recall with message/doc leniency, JSON+markdown reports (never
  one blended number), CLI, and papertrail-protocol v1 (PROTOCOL.md) for
  subprocess adapters with timeouts.
- Oracle adapter scores 100.0 accuracy and 100/100 citation P/R on every
  category of the committed 295-message fixture; refuse adapter scores 0.
  52 harness tests. Next: H2 baselines.

## Original B0 next-list (folded into plan-b1.md)

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

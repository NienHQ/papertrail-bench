# B1 plan: evaluation harness, full taxonomy, realism

Audience: anyone picking up work in this repo cold. Read this, then
[ground-truth-schema.md](ground-truth-schema.md) (the contract), then
[STATUS.md](STATUS.md). Work milestones in order; tasks inside a milestone
are independent unless a dependency is named.

Track 2 (corpsim/) is a separate workstream owned outside this plan: do not
modify anything under corpsim/ unless a task names it. Convergence of the
two tracks is milestone C, after B1.

## How to work on this repo

- Schema first: generator behavior changes update ground-truth-schema.md in
  the same change. The generator is the oracle; every scoring rule derives
  from its tables.
- Verify generator work: `cd generator && .venv/bin/python -m pytest`.
  Verify harness work: `cd harness && pnpm typecheck && pnpm test`.
- Determinism is the product: same seed, byte-identical corpus, on any
  machine. No wall clock, no environment reads, vendored word pools only.
- Never break B0 invariants (schema doc section 9); they are the test suite.
- Commits are plain, authored by the repo owner, no tool attribution.
- Keep new content free of em and en dashes.

## Current state (2026-07-17)

B0 done: Python generator, categories 1 to 3, 14 invariant tests, fixture
consumers exist (github.com/NienHQ/docket tests against a generated corpus).
Track 2 (CorpSim) merged. No harness, no baselines, no categories 4 to 7,
no realism screws, single-year corpora only.

## Milestone H: the harness (first, it unblocks the Docket ablations)

### H1. Harness core + oracle self-test
TypeScript package under `harness/` (pnpm, strict TS, vitest, Node >= 20).
- Corpus loader: messages/ + attachments/ for systems under test;
  ground_truth/ + questions.jsonl for the scorer (hard wall between them).
- Adapter interface: `ingest(corpusDir)` then per question
  `answer({id, category, text}) -> { answer, citations: string[] }` where a
  citation is a ground-truth-resolvable ref: a message id (with or without
  domain part), a doc id, or "messageId:statementId". In-process TS
  adapters plus a subprocess JSONL protocol (one request per line on
  stdin, one response per line on stdout) so Python/Docker systems plug in.
- Deterministic scorers per answer type (schema doc section 7): money and
  date normalization, string normalized-exact, int, ordered_list with LCS
  partial credit, abstention. No LLM judge anywhere in categories 1 to 3, 6.
- Citation scoring (category 7 axis, applied to every question): resolve
  predicted citations against the question's evidence set; report precision
  and recall; canonical vs quoted hits reported separately once quoted
  occurrences exist (G3).
- Report: per-category scores + citation metrics, JSON and markdown, never
  one blended number.
- Oracle adapter (reads ground truth) must score 100 percent on every
  category: the harness self-test. A "refuse everything" adapter must score
  100 percent on abstention only, once category 6 exists.
Done when: `pnpm papertrail-eval --corpus <dir> --adapter oracle` prints a
scorecard with 100s and the self-test runs in CI-less vitest.

### H2. Internal baselines
In harness/baselines/: bm25 (better-sqlite3 FTS5 over message bodies +
attachment text, top-k answer extraction with the simplest defensible
heuristics per template family), naive-vector (deterministic hash embedder
so runs are reproducible without models; document that real-model numbers
need an API), hybrid-rrf (both lists fused). Run all three plus oracle on a
committed small corpus and a regenerated default corpus; commit
docs/baselines-b0.md with the scorecards and exact reproduction commands.
Done when: the table exists, is reproducible from two commands, and bm25
beats naive-vector on category 1 or the doc explains why not.

### H3. Docket adapter (lives in the OTHER repo)
After H1 lands, Docket task 3.3 (github.com/NienHQ/docket docs/plan.md)
implements its adapter against the subprocess protocol and commits its
ablation table there. Bench-side work: freeze the protocol doc
(harness/PROTOCOL.md) and cut a tagged bench release the adapter pins.
Done when: protocol doc committed and tagged; the Docket repo runs it.

## Milestone G: taxonomy and realism (generator, Python)

### G1. Categories 4 and 6
Category 4 (cross-thread aggregation): INVOICE_DISPUTED / DISPUTE_RESOLVED
events with amounts and reasons, rendered as dispute threads; questions:
"total disputed amount with vendor X in FY", "how many invoices did we
dispute with X", "which invoices were disputed" (ordered_list). Answers
recompute from the event log via an independent path, as B0 does.
Category 6 (abstention): questions referencing plausible but nonexistent
vendors, invoices, POs (sampled from the same generators with ids that were
never issued); correct answer is refusal. Add both to the question sampler
with per-category counts in config.
Done when: default corpus emits 6 categories with >= 15 questions each and
all invariant tests still pass.

### G2. Category 5: entity resolution
CONTACT_CHANGED (new address, same person) and PERSON_MOVED (person changes
company mid-corpus) events; AddressPeriod windows already exist in the
schema. Render the change naturally (a "note my new address" line, then the
new address just starts appearing). Questions: "everything agreed with
<person> across addresses/companies" shapes with ordered_list or int
answers derivable from the log. Alias ground truth goes in people.jsonl as
B0 designed.
Done when: person-move questions answer correctly from ground truth and at
least one baseline demonstrably fails them (the gap is the point).

### G3. Realism screws (config flags, all default OFF, bench presets ON)
- truncated References headers (keep last N) and subject-only continuation
- quoted-reply duplication: quote earlier message bodies with "> "
  prefixes and emit occurrence: quoted evidence rows (schema already
  reserves the field); citation scoring then reports canonical-hit rate
- near-duplicate invoices (same vendor, same amount, one day apart, one
  voided by a correction email)
- people re-typing amounts with formatting drift ($1,250.00 vs 1250 USD)
Each screw is one flag + one test proving the ground truth stays exact.
Done when: a "hard" preset regenerates with all screws on and invariant
tests pass; harness scorecards show measurable degradation for bm25.

### G4. Scale: 3-year corpus
Multi-year event loop (year param becomes start_year + years), per-year
numbering series, renegotiations and lease amendments spread across years,
~15k messages at the default hard preset, 300+ questions. Generator must
stay under 2 minutes for the full corpus.
Done when: `--years 3` emits a valid corpus passing all invariants and the
bench preset docs update.

## Milestone C: convergence + launch (after B1, order flexible)

- Fold CorpSim's world model (payroll, bank, planted anomalies) into the
  Track 1 event-log schema so CorpSim answers carry citation provenance.
- Typst PDF attachments + rasterized-scan fraction (needs the schema's
  doc_field evidence granularity, already designed).
- Leaderboard page (static), paper-style README, external-system runs
  (the B2 launch from the original plan).

## Task claiming

Same convention as before: claim in STATUS.md when starting, move to a
done note when finished, keep schema doc / this plan / STATUS consistent
with the code.

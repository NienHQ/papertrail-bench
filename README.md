# PaperTrail-Bench

A long-horizon retrieval benchmark over a simulated company's multi-year email +
attachment corpus, with citation-correctness scoring.

**Status: early development (B0).** The corpus generator and ground-truth schema
are working; the question taxonomy is partial (3 of 7 categories) and the
evaluation harness does not exist yet. Nothing here is a stable interface.

## Two tracks, one thesis

Agents can't do finance work unless they can retrieve old records — and reason
over them — with provable provenance. The repo holds two complementary tracks
built on the same principle (*the generator is the oracle*: ground truth is
authored first, the messy corpus is rendered from it):

- **Track 1 — Retrieval & citation** (`generator/`, this README): can a system
  find the right record across years of email, respect amendment chains and
  temporal supersession, and cite the exact source message? Scored down to
  character spans.
- **Track 2 — CorpSim: operational finance QA** (`corpsim/`): a full 24-month
  company — 15 vendors, ~50 employees on payroll, 10 customers, one bank
  account — emitted as ~4,400 documents (negotiation email threads, POs,
  invoices, timesheets, payslips, chained bank statements) with a held-out
  SQLite truth DB and a programmatic judge. Can a system do the *bookkeeper's
  job*: 3-way matching, anomaly detection, aging, reconciliation, payroll
  totals? See [corpsim/README.md](corpsim/README.md).

The tracks share DNA and will converge: B1 folds CorpSim's richer world model
(payroll, banking, planted anomalies, negotiation narratives) into the
Track 1 event-log schema so every CorpSim answer also carries citation-level
provenance.

## Why

Agents can't do finance work unless they can retrieve old records with provable
provenance. No existing benchmark covers long-horizon *business correspondence*:
LongMemEval is chat history, FinanceBench is 10-K PDFs. PaperTrail-Bench asks the
questions a bookkeeper asks — "what did we agree with this vendor, as of this
date, and show me the exact message that says so" — over years of messy email.

## How it works

Ground truth is generated **first**, as a structured business event log (facts
with validity intervals, amendment chains, entity aliases). The email corpus is
rendered *from* the log — deliberately lossy and redundant. Every question is
computed from the log with a machine-checkable answer and an exact provenance
set, down to character spans in message bodies.

The design doc is **[docs/ground-truth-schema.md](docs/ground-truth-schema.md)**
— every scoring rule and generator invariant derives from it.

Question categories (each scored separately, never blended):

1. Specific record lookup ("what is the total of invoice INV-2024-0451?")
2. Lineage / amendment chains ("list every version of PO-2024-0113, in order")
3. Temporal supersession ("payment terms with vendor X *as of* 2024-09-01?")
4. Cross-thread aggregation *(planned)*
5. Entity resolution across addresses/companies *(planned)*
6. Abstention — the correct answer is "no such record" *(planned)*
7. Citation fidelity — did the system cite the exact source message/document?
   *(planned, applied to every question)*

## Quick start

Requires Python ≥ 3.12. No runtime dependencies.

```sh
cd generator
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m papertrail generate --seed 42 --out /tmp/corpus
.venv/bin/python -m pytest
```

The default config produces ~1.7k messages across ~500 threads, ~900 documents
with amendment chains, a fact ledger, and 50 questions with evidence sets.
Same seed ⇒ byte-identical corpus, on any machine.

## Layout

- `generator/` — Python corpus generator (`papertrail` package).
- `docs/` — schema design doc and status.
- `harness/` — TypeScript evaluation harness *(not yet started)*.

## Roadmap

- **B0 (done):** ground-truth schema + generator core; 1 company, 1 year,
  ~2k messages; 50 questions across categories 1–3.
- **B1:** full 7-category taxonomy + realism screws (truncated References
  headers, quoted-reply duplication, people changing addresses/companies,
  near-duplicate invoices, scanned PDFs at a configurable rate) + citation
  scoring; 3-year corpus, 300+ questions; harness + internal baselines
  (BM25/FTS5, naive vector, hybrid+RRF, long-context).
- **B2:** external-system adapters, leaderboard, paper-style writeup.

## License

MIT.

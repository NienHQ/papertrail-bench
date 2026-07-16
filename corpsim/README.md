# CorpSim — a synthetic company as an AI benchmark

*Track 2 of [PaperTrail-Bench](../README.md): operational finance QA. Track 1
benchmarks retrieval + citation over the correspondence; this track benchmarks
doing the bookkeeper's job on top of it.*

A deterministic generator that simulates **24 months (2024-07 → 2026-06) of a
fictional software-services company, Cobalt Peak Software Ltd.**, and emits
the full paper trail a finance/bookkeeping AI would face in the wild — plus a
held-out source of truth and a programmatic judge. All names and domains are
fictional (`.example` TLD); every number is synthetic.

The generator **is** the oracle: because it authored every event, it knows the
correct answer to every question it asks. AI systems are benchmarked by giving
them only the document mountain; the judge scores them against the key.

## The company

- ~50 employees (Delivery / Engineering / Sales / G&A), incl. 5 mid-sim hires
  and 2 exits. Monthly timesheets (manager-approved, some rejected and
  resubmitted) and monthly payroll with withholding + employer tax remittance.
- **15 vendors** (rent, cloud, SaaS, telecom, insurance, facilities, benefits,
  accounting, hardware, recruiting, legal, marketing, travel, catering,
  training): annual blanket agreements and ad-hoc POs, **negotiated over email
  threads**, signed, invoiced (per-vendor invoice numbering), paid per terms.
- **10 customers** buying software services (6 T&M engagements billed from the
  approved timesheet hours of assigned delivery teams; 4 retainers), invoiced
  monthly in arrears, with prompt / late / very-late payment behaviors,
  partial payments, and dunning emails.
- One operating bank account: every payment, receipt, payroll run, tax
  remittance and fee lands as a statement line; balances chain month to month.

### Planted anomalies (labeled in truth)

| kind             | story                                                             |
|------------------|-------------------------------------------------------------------|
| `overbilling`    | invoice exceeds PO-authorized amount; AP challenges by email, vendor amends, only the correct amount is paid |
| `duplicate`      | vendor resubmits an already-processed invoice; AP rejects it       |
| `missing_po_ref` | invoice arrives without a PO reference; resolved by email          |

Plus organic mess: variable cloud bills against a fixed blanket PO, prorated
payslips for mid-month hires/exits, rejected timesheets, partial customer
payments, open AP/AR at the cutoff.

## Layout

```
gen/                 the generator (stdlib-only Python)
out/docs/            ~4,400 files — ALL an AI under test may see
  emails/YYYY-MM/    ~1,400 .eml (negotiations, invoice submissions, AP
                     challenges, remittance advice, dunning, timesheet bounces)
  purchase_orders/   signed POs
  vendor_invoices/   invoices as submitted (incl. *__resubmitted duplicates)
  customer_invoices/ outbound invoices with per-consultant line items
  timesheets/        per-employee-month CSVs with approval trail
  payroll/           payslips + monthly registers
  bank_statements/   monthly CSV + summary, chained balances
  company/           employee directory, vendor list, client list
out/benchmark/questions.json   the exam (no answers)
out/truth/           HELD OUT: corpsim.db (SQLite, full ground truth)
                     + answers.json (the key)
judge.py             the judge
docs/benchmark-landscape.md    survey of prior art (what exists, the gap)
```

## Protocol

1. Give the system under test `out/docs/` and `out/benchmark/questions.json`.
   Nothing under `out/truth/` may be visible to it.
2. It writes `submission.json`: `{"Q001": <answer>, ...}`.
3. `python judge.py submission.json` → per-category and total score.
   Numbers score within a small tolerance, lists by set-F1, strings exact.

Question categories: vendor spend, procurement (negotiated savings), 3-way
match, anomaly detection, revenue, collections/aging, payroll, timesheets,
bank reconciliation.

## Regenerate / rescale

```
python -m gen.main                 # canonical bench (seed 20260716)
python -m gen.main --seed 7 --out out-7   # a fresh, unseen company
python selftest.py                 # determinism + judge self-test + corpus size
```

Requires Python ≥ 3.10, stdlib only. Same seed → byte-identical world. New
seed → new company, new key: unlimited contamination-free eval sets. The judge
self-test (submit the key itself) scores 100%.

## Why this exists

Nothing public combines an email-native narrative, the full
negotiation→PO→invoice→payment→bank chain, AP+AR+payroll+bank together, a
24-month horizon, and an open regenerable truth-DB judge — see
`docs/benchmark-landscape.md` for the survey (closest prior art:
AccountingBench, closed real data; FinBalance, single-period bundles).

# Synthetic-Corporation & Corporate-Finance Benchmarks for AI Systems — Landscape as of July 2026

(Deep-research survey, verified against live sources 2026-07-16. Context: CorpSim, this repo.)

## Executive summary

There is real activity in this space, and two things landed close to CorpSim's concept in the last 12 months: **AccountingBench** (Penrose, July 2025 — real 12-month startup books, monthly-close agent task, closed-source) and **FinBalance** (arXiv, June 2026 — synthetic document bundles with a programmatic ledger judge, but single-period, no emails, no payroll). Nothing combines a **multi-month email-native narrative** (negotiation → PO → invoice → payment chasing) with a **full double-sided company** (AP + AR + payroll + bank) and a **held-out truth DB + programmatic judge**.

---

## 1. Company / workplace simulation agent benchmarks

### TheAgentCompany — CMU et al., Dec 2024
- Simulated software company in Docker: self-hosted GitLab, OwnCloud, Plane, RocketChat, with LLM-simulated colleagues to talk to.
- 175 long-horizon tasks across SWE, PM, data science, admin, HR, and **finance** roles; finance tasks are small (fill a spreadsheet, check a reimbursement policy), not ledger work.
- **Judge:** yes — granular checkpoints + programmatic evaluators per task.
- **Temporal narrative:** no; each task is independent, no company timeline.
- Best agent ~30.3% completion (Gemini 2.5 Pro). https://arxiv.org/abs/2412.14161 · https://github.com/TheAgentCompany/TheAgentCompany · https://the-agent-company.com
- Derivative: **TheMCPCompany** (Oct 2025, task-specific MCP tools): https://arxiv.org/pdf/2510.19286

### WorkBench — Styles et al., COLM 2024 (+ "WorkBench Revisited", June 2026)
- Sandbox with 5 databases (calendar 300 events, inbox 500 emails, 500 analytics records, CRM with 200 customers, project board), 26 tools, 690 tasks.
- **Judge:** yes — outcome-centric: final database state compared to unique ground truth. Architecturally the closest precedent to CorpSim's "held-out truth DB" idea, but content is generic office work, not finance.
- **Temporal narrative:** no. GPT-4 solved 43%. https://arxiv.org/abs/2405.00823 · https://github.com/olly-styles/WorkBench · Revisited: https://arxiv.org/pdf/2606.13715

### τ-bench → τ²-bench → τ³-bench — Sierra, 2024–2026
- Tool-agent-user benchmark: simulated user + policy documents + database tools; **judged on final DB state + policy compliance** (pass^k reliability metric).
- τ³ (2026) adds a **banking domain** (~700 policy docs, ~195K tokens, disputes/freezes/provisional credits) plus telecom and a voice modality; no model exceeds 27% on Banking. Customer-service framing, not bookkeeping.
- https://arxiv.org/pdf/2406.12045 · https://github.com/sierra-research/tau2-bench (τ³ on `dev/tau3`) · leaderboard: https://artificialanalysis.ai/evaluations/tau3-banking

### CRMArena / CRMArena-Pro — Salesforce AI Research, 2024 / May 2025
- 19 expert-validated tasks over a **synthetically generated Salesforce org** (B2B and B2C schemas), multi-turn with personas, plus confidentiality-awareness tests. Relevant precedent for *synthetic enterprise data generation pipelines*.
- **Judge:** yes, per-task. **Temporal narrative:** no. Gemini 2.5 Pro ~58% single-turn, ~35% multi-turn. https://arxiv.org/abs/2505.18878 · https://www.salesforce.com/blog/crmarena-pro/ · https://huggingface.co/datasets/Salesforce/CRMArenaPro

### OfficeBench — July 2024, and OdysseyBench — Aug 2025
- OfficeBench: Word/Excel/email/calendar apps in Docker, multi-app workflows, exact/fuzzy/execution-based checks; GPT-4o 47%. https://arxiv.org/abs/2407.19056
- OdysseyBench: long-horizon office-app workflows built on top of it. https://arxiv.org/pdf/2508.09124
- PolyWorkBench (multilingual long-horizon, 2026): https://arxiv.org/pdf/2607.06008

### World of Workflows (WoW) — Skyfall Research, Jan 2026
- ServiceNow-based enterprise environment with **4,000+ business rules and 55 hidden workflows**; 234 tasks. Shows frontier LLMs have "dynamics blindness" — they can't predict cascading side effects in an opaque enterprise system. Judge: yes (state-based). No finance ledger, no temporal narrative. https://arxiv.org/abs/2601.22130 · https://github.com/Skyfall-Research/world-of-workflows

### ERP-Bench / Anchor — May 2026
- Agent tasks over ServiceNow, GitLab, and **ERPNext** (a real open-source ERP), generated with constraint-program solvers so tasks are well-specified and verifiable. Closest thing to an "ERPBench"; still single-task record manipulation, not month-over-month accounting. https://arxiv.org/pdf/2605.26321

### GDPval — OpenAI, Oct 2025 / APEX + APEX-Agents — Mercor, 2025–2026
- GDPval: 1,320 real-work tasks across 44 occupations **including accountants/bookkeepers** (spreadsheets, reports). **Judge: human expert graders**, not programmatic; one-shot deliverables, no longitudinal company. https://arxiv.org/pdf/2510.04374
- APEX: expert-authored cases for investment banking, law, consulting, medicine (top score in IB only 59.7%); APEX-Agents adds long-horizon agentic versions. Rubric/expert-graded. https://www.mercor.com/apex/ · https://arxiv.org/pdf/2601.14242

---

## 2. Finance / accounting benchmarks

### AccountingBench — Penrose Labs (NY), July 2025 — **closest existing thing, part 1**
- LLM agents must **close the books month by month for 12 months** of a real multi-million-ARR YC-backed SaaS business, given the same source feeds the real accountants had: **Ramp, Rippling, Stripe, Mercury**, against a simplified QuickBooks-style ledger.
- **Judge:** accuracy of resulting financial statements vs. a CPA human baseline; reconciliation checks against bank balances. Errors compound across months — the signature finding: Claude 4/Grok 4 start >95% and degrade below 85% (Grok collapses by month 5); Gemini 2.5 Pro/o3/o4-mini fail month 1. Models caught **fabricating plug transactions** to force reconciliation to pass.
- **Temporal narrative:** yes (12 months, compounding state) — but clean system feeds: **no email threads, no negotiations, no POs/3-way matching**, single company.
- **Not open-sourced** (confirmed in the HN thread). Real data, so hard to release and impossible to regenerate/scale. https://accounting.penrose.com/ · HN: https://news.ycombinator.com/item?id=44637352 · https://gigazine.net/gsc_news/en/20250724-accountingbench/

### FinBalance — BITS Pilani / KIIT / Oxford, June 2026 — **closest existing thing, part 2**
- **Synthetic, deterministically generated** multi-document accounting reconciliation benchmark: source-document bundles (invoices, bills, statements, payment notices, vouchers, contracts, rate sheets, accruals, opening trial balances, **distractors**) across 8 industries, 3 period types, 5 difficulty levels; 710 eval records; **23 labeled inconsistency codes** injected.
- **Judge:** yes, fully programmatic — a ledger generates ground-truth journal entries and balance sheets; scores BS_exact vs BS_recon (replaying model entries through the ledger).
- **Temporal narrative:** no — **single-period bundles**, not a continuous company. **No payroll, no email threads, no vendor negotiations**. Best model ≤46% exact balance-sheet accuracy.
- **Open**: Apache-2.0 code / CC-BY-4.0 data. https://arxiv.org/abs/2606.15949

### Audit-flavored 2025–2026 cluster
- **FinAuditing** (Oct 2025): 1,102 instances from real XBRL filings; LLM accuracy drops 60–90%. https://arxiv.org/abs/2510.08886
- **FinVerBench** (May 2026): financial-statement verification. https://arxiv.org/pdf/2605.29586
- **AuditFraudBench** (June 2026): detecting fraudulent misstatements. https://arxiv.org/pdf/2606.08345
- **AuditFlow** (June 2026): graph-grounded multi-agent auditor; deterministic checks are what makes it work (82% with them, 18% without) — a strong argument for the deterministic-judge design. https://arxiv.org/html/2606.03031

### Financial QA / reasoning benchmarks (static, no agent loop, no company)
- **FinanceBench** (Patronus/Contextual/Stanford, Nov 2023): 10,231 Qs over SEC filings. https://arxiv.org/abs/2311.11944 · https://github.com/patronus-ai/financebench
- **FinQA** (EMNLP 2021): 8,281 numeric-reasoning QA pairs. https://arxiv.org/abs/2109.00122
- **ConvFinQA** (EMNLP 2022): 3,892 conversational chains. https://arxiv.org/abs/2210.03849
- **TAT-QA** (ACL 2021): 16,552 hybrid table+text questions. https://arxiv.org/abs/2105.07624
- **BizBench** (Kensho, ACL 2024): 8 quantitative program-synthesis tasks. https://arxiv.org/abs/2311.06602 · https://benchmarks.kensho.com/
- **FinBen** (NeurIPS 2024 D&B): 24 tasks / 42 datasets. (A separate older "FinBench" covers tabular financial risk — names collide.) https://arxiv.org/abs/2402.12659
- **BizFinBench** (May 2025), **BigFinanceBench** (June 2026), **Finance Agent Benchmark** (Vals AI, Aug 2025) — analyst/research-facing, not bookkeeping. https://arxiv.org/abs/2505.19457 · https://arxiv.org/abs/2606.03829 · https://arxiv.org/abs/2508.00828

### Industry / startup activity — no public benchmarks found
- **Ramp** publishes internal LLM benchmarking (invoice OCR, statement extraction, autocoding, policy compliance) as blog posts, not a released dataset/harness. https://builders.ramp.com/post/financial-benchmarks
- **Basis** ($100M at $1.15B, Feb 2026), **Truewind**, **Numeric**, **Black Ore**, **Klarity**: no published benchmark or open eval harness from any of them. Nothing from Big-4 or Intuit as a public benchmark either.
- No "APBench", "BookkeepingBench", or ledger-reconciliation benchmark beyond FinBalance exists under those names; no benchmark for 3-way matching or aging reports specifically.

## 3. Invoice / document-extraction datasets (single-document, no reconciliation)

| Dataset | Maker / Year | Contents | Judge | URL |
|---|---|---|---|---|
| SROIE | ICDAR 2019 | ~1,000 scanned receipts, key-field extraction | field F1 | https://rrc.cvc.uab.es/?ch=13 |
| CORD | Clova AI, 2019 | ~11k receipts, post-OCR parsing | field/tree F1 | https://github.com/clovaai/cord |
| RVL-CDIP | 2015 | 400k doc images, 16-class classification | accuracy | https://adamharley.com/rvl-cdip/ |
| DocILE | Rossum, ICDAR 2023 | 6.7k annotated + 100k synthetic + ~1M unlabeled business docs | AP/F1 harness | https://github.com/rossumai/docile |
| GHEGA | Univ. Trieste, 2013 | small set of datasheets/patents | field extraction | https://machinelearning.inginf.units.it/data-and-tools/ghega-dataset |

All are per-document extraction; none link a PO to its invoice to its payment. DocILE's synthetic-document generator is useful prior art for realistic rendering.

## 4. Synthetic ERP / demo datasets (prior art, not benchmarks)

- **SAP IDES** — SAP's model-company training client; full ERP transactions, no source-document mess, no judge.
- **Microsoft AdventureWorks / Contoso** — sample OLTP/DW databases. Clean relational state only. https://learn.microsoft.com/en-us/sql/samples/adventureworks-install-configure
- **Odoo demo data**, **QuickBooks sample companies** ("Craig's Design & Landscaping"), **Xero demo company** — pre-populated books for training.

Common shape: they hand you the *answer* (a consistent ERP state) with no held-out truth, no messy multi-document/email narrative, no scoring harness. CorpSim inverts this: give the agent the mess, hold out the state.

## 5. Academic synthetic-financial-data generation

Sparse. FinBalance's deterministic scenario→documents→ledger generator is the main directly relevant example. Adjacent: StructText (https://arxiv.org/pdf/2507.21340), CRMArena-Pro's synthetic-org pipeline, DocILE's synthetic invoices, MANTRA (https://arxiv.org/pdf/2605.06334), Anchor's constraint-solver task generation. Nobody has published a generator for a *coherent multi-month company* with correlated emails, documents, and bank flows.

---

## Gap analysis — what CorpSim provides that does not exist

Being honest about what's close: **AccountingBench proves the "longitudinal close with compounding errors" concept** and **FinBalance proves the "synthetic documents + programmatic ledger judge" concept**. CorpSim is essentially the union of the two plus several things neither has. No existing artifact offers:

1. **Email-native narrative.** No benchmark anywhere contains vendor negotiation threads, payment follow-ups, or any email trail an agent must mine to explain a price variance or a partial payment. The single most defensible gap.
2. **The full P2P chain as a scoreable object.** Negotiation → PO → invoice → payment → bank line. Nobody scores 3-way matching at all.
3. **A double-sided company: AP + AR + payroll + bank simultaneously.** Nothing has employee timesheets → payroll runs as an evaluable flow.
4. **24-month horizon.** The longest existing horizon is AccountingBench's 12 months.
5. **Held-out ground-truth DB + open programmatic judge over operational reports** (aging, reconciliation status, anomaly-detection recall against injected labeled anomalies — FinBalance's 23 inconsistency codes are the nearest precedent).
6. **Open and regenerable.** AccountingBench is closed real data (unreleasable, contamination-prone). A synthetic generator gives unlimited fresh companies, difficulty dials, and contamination resistance.

Caveats: (a) watch FinBalance's authors — a "FinBalance-v2 with temporal chains" is the obvious next paper; (b) Penrose is pushing down this research direction and may release; (c) AuditFlow's ablation (82% → 18% without deterministic checks) is strong published evidence for making the deterministic judge the centerpiece.

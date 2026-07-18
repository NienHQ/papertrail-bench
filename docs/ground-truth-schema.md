# PaperTrail-Bench: ground-truth event-log schema

Status: B0 draft (2026-07-15). This is the load-bearing design doc: every scoring
rule in the harness and every table in the reference engine derives from the
structures defined here. Change this file first, code second.

## 1. The derivation rule

Ground truth is generated **first**, as a structured business event log. The
email/attachment corpus is a *rendering* of that log — deliberately lossy, messy,
and redundant. Questions and answers are computed from the log, never from the
rendered corpus. This gives every question:

1. a machine-checkable answer (typed value, computed from tables), and
2. an exact provenance set (which message statements / document fields state the
   supporting facts, down to character spans).

The direction of derivation is one-way:

```
seed → world → event log → { documents, fact ledger }   (deterministic views)
                        → communication plan → rendered corpus (.eml + attachments)
event log + views → questions + answers + evidence sets
```

A system under test sees only the rendered corpus. The harness sees everything.

## 2. Determinism

- Single integer seed drives everything via `random.Random(seed)`. No wall clock,
  no environment reads, no third-party data generators (name/company/item pools are
  vendored word lists), so a corpus is byte-reproducible across machines and time.
- All IDs are deterministic, prefixed, zero-padded sequence numbers:
  `PTY-0001` (party), `PER-0001` (person), `EVT-000001` (event), `FCT-000001`
  (fact), `THR-0001` (thread), `MSG-000001` (message), `Q-0001` (question).
  Business document numbers look like real ones: `PO-2024-0113`, `INV-2024-0451`,
  `CN-2024-0007`; amended versions append `-A1`, `-A2`, …
- Email `Message-ID` headers are `<MSG-000123@domain>` — derived, never random.
  MIME boundaries are derived from the message ID.
- `manifest.json` records seed, config, generator version, per-file SHA-256 and
  counts. The determinism test regenerates and compares hashes.

## 3. Layer 0 — world

The simulated SME ("us") plus its counterparties.

**Party** — `{party_id, kind, name, domain, is_self}`
`kind ∈ {self, vendor, customer, landlord, bank, payroll}`. Exactly one party has
`is_self = true`. Domains use invented names under `.example` in B0 (realistic TLD
collisions and lookalike domains are a B1 realism screw for entity resolution).

**Person** — `{person_id, name, party_id, addresses: [AddressPeriod]}`
`AddressPeriod = {address, from_date, to_date|null}`. Periods are non-overlapping
and cover the person's active span. In B0 each person has one address for the whole
year; the period structure exists so B1 can introduce address changes and company
moves (question category 5, entity resolution) without a schema change.

## 4. Layer 1 — the event log

The canonical timeline. Everything else is a view over it.

**Event envelope** — `{event_id, event_time (UTC datetime), type, actor_party,
counterparty, payload, refs}`
`refs` names the business objects an event touches (`{"doc": "PO-2024-0113"}`,
`{"invoice": "INV-2024-0451"}`); `payload` carries type-specific fields. Events are
strictly ordered by `(event_time, event_id)`.

**Event type catalog (B0 subset)**

| type | payload | produces |
|---|---|---|
| `TERMS_AGREED` | `{relation: "payment_terms", value: "NET30"}` | fact (supersession chain) |
| `PRICE_AGREED` | `{relation: "unit_price:<item>", value_cents, item}` | fact |
| `LEASE_SIGNED` | `{monthly_rent_cents, term_months}` | doc + `monthly_rent` fact |
| `LEASE_AMENDED` | `{monthly_rent_cents}` | doc version + fact supersession |
| `PO_ISSUED` | `{item, qty, unit_price_cents, total_cents}` | doc (chain root) |
| `PO_AMENDED` | changed fields | doc version |
| `INVOICE_ISSUED` | `{total_cents, po_ref, due_date}` | doc |
| `CREDIT_NOTE_ISSUED` | `{amount_cents, invoice_ref, reason}` | doc |
| `PAYMENT_SENT` / `PAYMENT_RECEIVED` | `{amount_cents, invoice_ref, method}` | — |
| `INVOICE_DISPUTED` | `{invoice_ref, disputed_cents, reason}` | dispute thread (category 4) |
| `DISPUTE_RESOLVED` | `{invoice_ref, resolution: credit_note\|withdrawn, credit_note_ref?}` | closes the dispute |

Dispute consistency rule: a dispute resolved as `credit_note` produces a
`CREDIT_NOTE_ISSUED` for the disputed amount against the same invoice, and the
payment reflects it; a dispute resolved as `withdrawn` changes no amounts.
Category 4 aggregates ("total disputed with vendor X in the fiscal year")
recompute from `INVOICE_DISPUTED` events alone.

B1 adds next: `CONTACT_CHANGED` / `PERSON_MOVED` (category 5 entity
resolution), payroll and bank statement events. The envelope does not change.

**Internal consistency rule:** derived values inside events must agree with the
ledger as-of the event time. Example: an invoice's `due_date` = issue date + the
payment terms fact valid at issue. This is what makes temporal questions (category
3) honest — the corpus itself behaves as if the superseded fact was real.

## 5. Layer 2 — deterministic views

### 5.1 Documents and version chains

**Document** — `{doc_id, kind, root_id, version, supersedes, party_id, issued_date,
fields, created_event}`
`kind ∈ {po, invoice, credit_note, lease}`. A "changed" document is a new row:
`PO-2024-0113` (v1, `supersedes: null`) ← `PO-2024-0113-A1` (v2) ← `-A2` (v3), all
sharing `root_id = PO-2024-0113`. Lineage questions (category 2) are answered by
ordering a root's rows by version. Chains are acyclic by construction and version
order equals event-time order.

`fields` is the full current state of the document at that version (not a delta), so
category-1 lookups read one row.

### 5.2 Fact ledger

**Fact** — `{fact_id, entity (party_id), relation, value, valid_from, valid_to|null,
source_event}`

Structural keying: the key is `(entity, relation)`. A new event with an existing key
closes the previous fact (`valid_to := new valid_from`) and opens a new one —
*superseded, never deleted*. Relations in B0: `payment_terms`,
`unit_price:<item>`, `monthly_rent`.

Ground truth is single-temporal (event time only). Ingestion time — the other half
of the bi-temporal model — belongs to the system under test; the bench manipulates
it only through *corpus presentation order* (B1 screw: shuffled/backfilled delivery,
the Graphiti #1489 scenario), which needs no schema change here.

Category-3 questions resolve `(entity, relation, as_of)` against this table:
the fact with `valid_from ≤ as_of < valid_to` (or open-ended).

## 6. Layer 3 — communications

Each event renders to zero or more messages via a per-type communication script
(e.g. `PO_ISSUED` → buyer sends PO with attachment, vendor acks;
`TERMS_AGREED` (renegotiation) → 3-message thread: request, counter, agreement).

**Thread** — `{thread_id, subject, participants, root_message}`
**Message** — `{message_id, thread_id, ts, from_person, from_address, to, subject,
in_reply_to, references[], attachments[doc_id], body}`

Threading headers are generated correctly in B0 (full `References` chains); B1
screws truncate/mangle them and add subject-only continuation, per JWZ.

### 6.1 Statements and spans

A message body is composed of ordered **statements** — human-prose sentences that
each assert zero or more ground-truth targets:

**StatementOccurrence** — `{message_id, statement_id, span: [start, end),
occurrence: canonical|quoted, targets: [TargetRef]}`
**TargetRef** — `{"fact": fact_id}` | `{"event": event_id}` |
`{"doc_field": [doc_id, field]}`

Spans are **character offsets into the decoded text/plain body** of the message
(not raw EML bytes — MIME transfer encoding must not affect ground truth). The
invariant `body[start:end] == statement_text` is machine-checked.

`occurrence` distinguishes the original assertion (`canonical`) from quoted-reply
copies (`quoted`). B0 emits only canonical occurrences; B1's quoted-reply
duplication screw adds `quoted` rows. Scoring rule fixed now: citing a quoted copy
of the right statement is **correct** (the bytes do support the answer) but
leaderboards also report canonical-hit rate separately.

### 6.2 Attachments

Attachments are rendered from document rows. B0 renders text/plain documents
(deterministic bytes, content-addressed by SHA-256, deduplicated on disk); B1 adds
Typst-rendered PDFs and the rasterized-scan screw. Attachment evidence is
field-anchored (`doc_field` targets), not span-anchored — a PDF has no stable char
offsets. The evidence granularity for attachments is `(doc_id, field)`; for message
bodies it is `(message_id, span)`.

## 7. Layer 4 — questions

**Question** — `{question_id, category, template, text, answer, evidence:
[EvidenceRef], params}`

**Answer** is typed; scoring is deterministic per type:

| type | value | scoring |
|---|---|---|
| `money` | `{amount_cents, currency}` | exact after normalization (parse "$1,250.00", "1250 USD") |
| `date` | ISO date | exact after normalization |
| `string` | canonical string | normalized exact (case/whitespace); no LLM judge in cats 1–3 |
| `int` | integer | exact |
| `ordered_list` | `[doc_id, …]` | exact sequence; partial credit = normalized longest-common-subsequence |
| `abstain` | — | correct iff the system declines to answer |

**EvidenceRef** — `{message_id, statement_id}` (resolvable to span) or
`{doc_id, field}`. Citation scoring (category 7 axis, applied to every question):
predicted citations are resolved to targets; a citation is a hit if it lands in the
question's evidence set (canonical or quoted, reported separately). Precision and
recall over the evidence set are both published.

**Categories (B0 shipped 1-3; G1 adds 4 and 6):**
1. *Specific record lookup* — sampled from document rows ("What is the total amount
   of invoice INV-2024-0451?", "Which PO does it reference?", "When was it issued?").
2. *Lineage* — sampled from version chains with ≥2 versions ("List all versions of
   PO-2024-0113 in order", "How many times was it amended?", "What was the final
   agreed quantity?").
3. *Temporal supersession* — sampled from `(entity, relation)` keys with ≥2 facts,
   with `as_of` dates drawn both before and after each supersession boundary ("What
   were the payment terms with Vendor X as of 2024-09-01?").
4. *Cross-thread aggregation* — computed over `INVOICE_DISPUTED` events per
   counterparty ("total disputed amount with Vendor X this year" → money,
   "how many invoices did we dispute with X" → int, "which invoices were
   disputed with X, in order" → ordered_list). Evidence = the canonical
   dispute statements of every contributing event.
5. *(reserved: entity resolution, G2)*
6. *Abstention* — questions referencing plausible but never-issued ids
   (invoice/PO numbers beyond the issued series, company names drawn from
   the unused name pool). Correct answer is refusal; the evidence set is
   empty by definition, and citation metrics skip such questions.
7. *(citation fidelity is an axis on every question, scored by the harness)*

Per-category question counts are config (`category_counts`); the default
config emits at least 15 questions in every shipped category.

Every generated question is verified answerable: the generator recomputes the answer
from the tables through an independent code path and asserts equality, and asserts
the evidence set is non-empty and resolvable.

## 8. Corpus directory layout

```
corpus/
  manifest.json               seed, config, generator version, counts, file hashes
  messages/MSG-000001.eml …   RFC822, one file per message
  attachments/<sha256>        content-addressed attachment bodies (deduplicated)
  ground_truth/
    parties.jsonl  people.jsonl  events.jsonl  documents.jsonl  facts.jsonl
    threads.jsonl  messages.jsonl  evidence.jsonl
  questions.jsonl
```

Systems under test get `messages/` + `attachments/` only. `ground_truth/` and
`questions.jsonl` (answers + evidence) are the harness's side of the wall.

## 9. Machine-checked invariants (generator test suite)

1. Same seed ⇒ byte-identical corpus (hash of every file).
2. Every fact has ≥1 canonical statement occurrence in some message.
3. Every question's answer recomputes identically via an independent path; every
   evidence ref resolves.
4. Span integrity: `decoded_body[start:end] == statement_text` for every occurrence.
5. Version chains: acyclic, contiguous versions, event-time ordered; `supersedes`
   agrees with version order.
6. Fact ledger: per `(entity, relation)`, intervals are non-overlapping, contiguous
   at supersession boundaries, exactly one open interval.
7. Alias periods per person: non-overlapping.
8. Internal consistency: invoice due dates match the terms fact as-of issue date.
9. Every message parses as RFC822 with resolvable threading headers (B0).

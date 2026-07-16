# PaperTrail adapter protocol, v1

This document is the contract between the PaperTrail harness and any system
under test. It covers the subprocess wire protocol ("papertrail-protocol
v1"), the in-process adapter interface, the citation forms the scorer
resolves, and the normalization rules applied to answers. External adapters
should pin the bench release that ships this file.

## 1. What an adapter sees

Adapters receive the messages directory and the attachments directory of a
corpus, nothing else. `ground_truth/` and `questions.jsonl` are the
harness's side of the wall; reading them from disk is cheating and
disqualifies a run. The `corpusDir` field in the ingest message exists only
so adapters can resolve corpus-relative paths.

## 2. In-process adapters (TypeScript)

```ts
interface Adapter {
  name: string;
  ingest(corpus: SystemCorpus): Promise<void>;
  answer(q: { id: string; category: number; text: string }): Promise<{
    answer: unknown;
    citations: string[];
  }>;
  close?(): Promise<void>;
}
```

`SystemCorpus` is `{ messagesDir, attachmentsDir }`. The CLI loads a module
adapter from a path given to `--adapter`: the default export must be an
`Adapter` object or a zero-argument factory function returning one.

## 3. Subprocess wire protocol ("papertrail-protocol v1")

Transport: newline-delimited JSON. Exactly one JSON object per line, UTF-8,
`\n` terminated, runner to adapter on stdin, adapter to runner on stdout.
Stderr passes through to the harness's stderr untouched; use it freely for
logging. Nothing but protocol lines may be written to stdout.

Message sequence:

1. Runner sends:

   ```json
   {"type": "ingest", "protocol": "papertrail-protocol v1",
    "corpusDir": "...", "messagesDir": "...", "attachmentsDir": "..."}
   ```

   The adapter ingests the corpus and replies `{"type": "ready"}` when it
   is prepared to answer questions.

2. For each question, runner sends:

   ```json
   {"type": "question", "id": "Q-0001", "category": 1, "text": "..."}
   ```

   The adapter replies:

   ```json
   {"type": "answer", "id": "Q-0001", "answer": <see section 5>,
    "citations": ["MSG-000012:MSG-000012-S1", "INV-2024-0007"]}
   ```

   Questions are sent sequentially; the `id` in the reply must echo the
   question id. A late reply to a question that already timed out is
   discarded.

3. Runner sends `{"type": "shutdown"}`. The adapter should exit; after a
   2 second grace period it is killed.

Timeouts: 10 minutes for ingest, 60 seconds per question. On a timeout, an
unparseable stdout line, or a malformed message, the affected question
scores 0 and the report lists the reason in its notes; the run continues
with the next question.

## 4. Citations

Citations are strings resolved against ground truth. Accepted forms:

| form | example | resolves to |
|---|---|---|
| bare message id | `MSG-000012` | message |
| message id with domain | `MSG-000012@x.example` | message (domain stripped) |
| message id + statement id | `MSG-000012:MSG-000012-S1` | statement |
| bare statement id | `MSG-000012-S1` | statement |
| doc id | `INV-2024-0007` | document |

Angle brackets copied from a raw `Message-ID` header
(`<MSG-000012@x.example>`) are tolerated and stripped. In the colon form,
an unknown statement id after a known message id falls back to
message-level resolution. Anything else is unresolved: it still counts
against precision and can never hit.

Scoring, applied to every question:

- A question's evidence set is a list of refs, each either
  `{message_id, statement_id}` or `{doc_id, field}`.
- Predicted citations are resolved, then deduplicated.
- A statement-level prediction hits the evidence ref with that statement
  id. A message-level prediction hits every evidence statement of that
  message: citing the whole message is accepted as citing each of its
  evidence statements. Likewise a doc-level prediction hits every
  `{doc_id, field}` ref of that doc. This leniency is deliberate for v1.
- Precision = predictions that hit at least one evidence item / distinct
  predictions. Recall = distinct evidence items hit / total evidence items.
  Both are micro-averaged per category and overall.
- Canonical vs quoted occurrences are NOT yet split: current corpora only
  emit canonical statement occurrences. Once quoted occurrences exist, the
  canonical hit rate will be reported separately; the evidence rows already
  reserve the `occurrence` field for this.

## 5. Answer normalization

Scoring is deterministic per answer type. No LLM judge anywhere in
categories 1 to 3 and 6.

- **money**: accepted shapes: `{"amount_cents": 125000, "currency": "USD"}`,
  `"$1,250.00"`, `"1250 USD"`, `"USD 1,250"`, `"1,250.00 USD"`, or a plain
  number in major units (`1250`). Everything is normalized to integer cents
  and compared exactly. The `$` symbol implies USD; a prediction with no
  currency marker matches any expected currency. More than two decimal
  places is a parse failure.
- **date**: normalized to ISO `YYYY-MM-DD` and compared exactly. Accepted:
  ISO dates (an ISO date followed by a time is truncated to its date part)
  and month-name forms (`"Feb 6, 2024"`, `"February 6 2024"`,
  `"6 Feb 2024"`). Numeric slash forms such as `"06/02/2024"` are AMBIGUOUS
  (day/month vs month/day) and are always rejected, scoring 0. Send ISO.
- **string**: compared exactly after trimming, lowercasing, and collapsing
  internal whitespace runs to single spaces.
- **int**: exact integer equality; digit strings (optionally with comma
  grouping) are coerced. Non-integers fail.
- **ordered_list**: a JSON array of strings. A string splitting cleanly on
  commas or newlines is tolerated. Exact sequence match scores 1.0;
  otherwise partial credit is longest-common-subsequence length divided by
  the expected length. Items are normalized like strings.
- **abstain** (category 6): correct iff the adapter refuses. Accepted
  refusal shapes: `null`, the empty string, `{"abstain": true}`, or one of
  these strings after string normalization and stripping trailing `.` or
  `!`: `abstain`, `abstained`, `refuse`, `refused`, `unknown`, `none`,
  `n/a`, `no answer`, `cannot answer`, `can't answer`, `not found`,
  `no record`, `no such record`, `insufficient evidence`,
  `insufficient information`, `i don't know`, `i do not know`.
  Any other value on an abstention question scores 0, and any refusal
  shape on a non-abstention question scores 0.

## 6. Report

The harness emits a JSON report and a markdown scorecard: per-category N
and accuracy (mean per-question score), citation precision and recall per
category and overall, plus per-question rows and notes for timeouts and
protocol errors. There is never a single blended number.

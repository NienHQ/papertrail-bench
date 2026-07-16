import type {
  EvidenceRef,
  MoneyValue,
  Question,
  QuestionAnswer,
  TruthCorpus,
} from "./corpus.js";
import { isMessageEvidenceRef } from "./corpus.js";

/* ------------------------------------------------------------------ */
/* Money                                                               */
/* ------------------------------------------------------------------ */

export interface ParsedMoney {
  amountCents: number;
  /** null means the prediction carried no currency marker. */
  currency: string | null;
}

function parseMoneyString(input: string): ParsedMoney | null {
  let s = input.trim();
  let currency: string | null = null;

  const leading = /^([A-Za-z]{3})\s*/.exec(s);
  if (leading !== null && leading[1] !== undefined) {
    currency = leading[1].toUpperCase();
    s = s.slice(leading[0].length);
  } else {
    const trailing = /\s*([A-Za-z]{3})$/.exec(s);
    if (trailing !== null && trailing[1] !== undefined) {
      currency = trailing[1].toUpperCase();
      s = s.slice(0, s.length - trailing[0].length);
    }
  }
  s = s.trim();

  let negative = false;
  if (s.startsWith("-")) {
    negative = true;
    s = s.slice(1).trim();
  }
  if (s.startsWith("$")) {
    if (currency === null) currency = "USD";
    s = s.slice(1).trim();
  }
  if (s.startsWith("-")) {
    negative = true;
    s = s.slice(1).trim();
  }

  const m = /^(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{1,2}))?$/.exec(s);
  if (m === null || m[1] === undefined) return null;
  const whole = Number(m[1].replaceAll(",", ""));
  const frac = m[2] ?? "";
  const cents = whole * 100 + (frac.length === 0 ? 0 : Number(frac.padEnd(2, "0")));
  return { amountCents: negative ? -cents : cents, currency };
}

/**
 * Normalize a predicted money value to integer cents plus an optional
 * currency. Accepts "$1,250.00", "1250 USD", "USD 1,250", plain numbers
 * (major units), and {amount_cents, currency} objects.
 */
export function parseMoney(value: unknown): ParsedMoney | null {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    return { amountCents: Math.round(value * 100), currency: null };
  }
  if (typeof value === "string") return parseMoneyString(value);
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>;
    const cents = obj["amount_cents"];
    if (typeof cents === "number" && Number.isFinite(cents)) {
      const cur = obj["currency"];
      return {
        amountCents: Math.round(cents),
        currency: typeof cur === "string" ? cur.toUpperCase() : null,
      };
    }
  }
  return null;
}

export function scoreMoney(expected: MoneyValue, predicted: unknown): number {
  const parsed = parseMoney(predicted);
  if (parsed === null) return 0;
  if (parsed.amountCents !== expected.amount_cents) return 0;
  if (parsed.currency !== null && parsed.currency !== expected.currency.toUpperCase()) {
    return 0;
  }
  return 1;
}

/* ------------------------------------------------------------------ */
/* Date                                                                */
/* ------------------------------------------------------------------ */

const MONTHS: Record<string, number> = {
  jan: 1, january: 1,
  feb: 2, february: 2,
  mar: 3, march: 3,
  apr: 4, april: 4,
  may: 5,
  jun: 6, june: 6,
  jul: 7, july: 7,
  aug: 8, august: 8,
  sep: 9, sept: 9, september: 9,
  oct: 10, october: 10,
  nov: 11, november: 11,
  dec: 12, december: 12,
};

function isoDate(y: number, mo: number, d: number): string | null {
  if (!Number.isInteger(y) || !Number.isInteger(mo) || !Number.isInteger(d)) return null;
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${String(y)}-${pad(mo)}-${pad(d)}`;
}

/**
 * Normalize a predicted date to ISO YYYY-MM-DD. Accepts ISO dates (with or
 * without a time suffix) and month-name forms ("Feb 6, 2024", "6 Feb 2024").
 * Numeric slash forms ("06/02/2024") are AMBIGUOUS and always rejected.
 */
export function parseDate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const s = value.trim();
  if (s.includes("/")) return null;

  let m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$/.exec(s);
  if (m !== null && m[1] !== undefined && m[2] !== undefined && m[3] !== undefined) {
    return isoDate(Number(m[1]), Number(m[2]), Number(m[3]));
  }

  m = /^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(\d{4})$/.exec(s);
  if (m !== null && m[1] !== undefined && m[2] !== undefined && m[3] !== undefined) {
    const mo = MONTHS[m[1].toLowerCase()];
    if (mo === undefined) return null;
    return isoDate(Number(m[3]), mo, Number(m[2]));
  }

  m = /^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?\s*,?\s*(\d{4})$/.exec(s);
  if (m !== null && m[1] !== undefined && m[2] !== undefined && m[3] !== undefined) {
    const mo = MONTHS[m[2].toLowerCase()];
    if (mo === undefined) return null;
    return isoDate(Number(m[3]), mo, Number(m[1]));
  }

  return null;
}

export function scoreDate(expected: string, predicted: unknown): number {
  const parsed = parseDate(predicted);
  return parsed !== null && parsed === expected ? 1 : 0;
}

/* ------------------------------------------------------------------ */
/* String                                                              */
/* ------------------------------------------------------------------ */

export function normalizeString(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

export function scoreString(expected: string, predicted: unknown): number {
  if (typeof predicted !== "string" && typeof predicted !== "number") return 0;
  return normalizeString(String(predicted)) === normalizeString(expected) ? 1 : 0;
}

/* ------------------------------------------------------------------ */
/* Int                                                                 */
/* ------------------------------------------------------------------ */

export function parseInteger(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isInteger(value) ? value : null;
  }
  if (typeof value === "string") {
    const s = value.trim();
    if (/^[+-]?\d+$/.test(s)) return Number(s);
    if (/^[+-]?\d{1,3}(?:,\d{3})+$/.test(s)) return Number(s.replaceAll(",", ""));
  }
  return null;
}

export function scoreInt(expected: number, predicted: unknown): number {
  return parseInteger(predicted) === expected ? 1 : 0;
}

/* ------------------------------------------------------------------ */
/* Ordered list                                                        */
/* ------------------------------------------------------------------ */

export function lcsLength(a: string[], b: string[]): number {
  const rows = a.length;
  const cols = b.length;
  let prev = new Array<number>(cols + 1).fill(0);
  for (let i = 1; i <= rows; i++) {
    const cur = new Array<number>(cols + 1).fill(0);
    for (let j = 1; j <= cols; j++) {
      if (a[i - 1] === b[j - 1]) {
        cur[j] = (prev[j - 1] ?? 0) + 1;
      } else {
        cur[j] = Math.max(prev[j] ?? 0, cur[j - 1] ?? 0);
      }
    }
    prev = cur;
  }
  return prev[cols] ?? 0;
}

function toStringList(value: unknown): string[] | null {
  if (Array.isArray(value)) {
    const out: string[] = [];
    for (const item of value) {
      if (typeof item !== "string" && typeof item !== "number") return null;
      out.push(String(item));
    }
    return out;
  }
  if (typeof value === "string") {
    return value
      .split(/[,\n]+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }
  return null;
}

/**
 * Exact sequence scores 1.0; otherwise partial credit is the length of the
 * longest common subsequence divided by the expected length.
 */
export function scoreOrderedList(expected: string[], predicted: unknown): number {
  const list = toStringList(predicted);
  if (list === null || expected.length === 0) return 0;
  const e = expected.map(normalizeString);
  const p = list.map(normalizeString);
  if (e.length === p.length && e.every((v, i) => v === p[i])) return 1;
  return lcsLength(e, p) / e.length;
}

/* ------------------------------------------------------------------ */
/* Abstention                                                          */
/* ------------------------------------------------------------------ */

const REFUSAL_STRINGS = new Set([
  "",
  "abstain",
  "abstained",
  "refuse",
  "refused",
  "unknown",
  "none",
  "n/a",
  "no answer",
  "cannot answer",
  "can't answer",
  "not found",
  "no record",
  "no such record",
  "insufficient evidence",
  "insufficient information",
  "i don't know",
  "i do not know",
]);

/** The accepted refusal shapes; the canonical list lives in PROTOCOL.md. */
export function isAbstention(predicted: unknown): boolean {
  if (predicted === null || predicted === undefined) return true;
  if (typeof predicted === "string") {
    const n = normalizeString(predicted).replace(/[.!]+$/, "").trim();
    return REFUSAL_STRINGS.has(n);
  }
  if (typeof predicted === "object" && !Array.isArray(predicted)) {
    return (predicted as Record<string, unknown>)["abstain"] === true;
  }
  return false;
}

/* ------------------------------------------------------------------ */
/* Dispatch                                                            */
/* ------------------------------------------------------------------ */

export function scoreAnswer(expected: QuestionAnswer, predicted: unknown): number {
  switch (expected.type) {
    case "money":
      return scoreMoney(expected.value as MoneyValue, predicted);
    case "date":
      return scoreDate(expected.value as string, predicted);
    case "string":
      return scoreString(expected.value as string, predicted);
    case "int":
      return scoreInt(expected.value as number, predicted);
    case "ordered_list":
      return scoreOrderedList(expected.value as string[], predicted);
    case "abstain":
      return isAbstention(predicted) ? 1 : 0;
    default:
      return 0;
  }
}

/* ------------------------------------------------------------------ */
/* Citations                                                           */
/* ------------------------------------------------------------------ */

export type ResolvedCitation =
  | { kind: "statement"; statementId: string; messageId: string }
  | { kind: "message"; messageId: string }
  | { kind: "doc"; docId: string }
  | { kind: "unresolved"; raw: string };

function stripDomain(id: string): string {
  const at = id.indexOf("@");
  return at >= 0 ? id.slice(0, at) : id;
}

/**
 * Normalize a predicted citation string to a ground-truth entity. Accepted
 * forms: bare message id, message id with domain, "messageId:statementId",
 * bare statement id, doc id. Angle brackets from raw Message-ID headers are
 * tolerated. An unknown statement id after a known message id falls back to
 * message-level resolution.
 */
export function resolveCitation(raw: string, truth: TruthCorpus): ResolvedCitation {
  let s = raw.trim();
  if (s.startsWith("<") && s.endsWith(">")) s = s.slice(1, -1).trim();

  const colon = s.indexOf(":");
  if (colon >= 0) {
    const left = stripDomain(s.slice(0, colon).trim());
    const right = s.slice(colon + 1).trim();
    const statement = truth.statements.get(right);
    if (statement !== undefined) {
      return {
        kind: "statement",
        statementId: statement.statement_id,
        messageId: statement.message_id,
      };
    }
    if (truth.messages.has(left)) return { kind: "message", messageId: left };
    return { kind: "unresolved", raw };
  }

  const statement = truth.statements.get(s);
  if (statement !== undefined) {
    return {
      kind: "statement",
      statementId: statement.statement_id,
      messageId: statement.message_id,
    };
  }
  const messageId = stripDomain(s);
  if (truth.messages.has(messageId)) return { kind: "message", messageId };
  if (truth.documents.has(s)) return { kind: "doc", docId: s };
  return { kind: "unresolved", raw };
}

function citationKey(c: ResolvedCitation): string {
  switch (c.kind) {
    case "statement":
      return `s:${c.statementId}`;
    case "message":
      return `m:${c.messageId}`;
    case "doc":
      return `d:${c.docId}`;
    case "unresolved":
      return `u:${c.raw}`;
  }
}

function evidenceKey(ref: EvidenceRef): string {
  return isMessageEvidenceRef(ref)
    ? `s:${ref.statement_id}`
    : `d:${ref.doc_id}#${ref.field}`;
}

export interface CitationScore {
  /** Distinct resolved predictions (deduplicated). */
  predicted: number;
  /** Predictions that hit at least one evidence item. */
  hits: number;
  /** Distinct evidence items in the question's evidence set. */
  evidenceTotal: number;
  /** Distinct evidence items hit by at least one prediction. */
  evidenceHit: number;
}

/**
 * Score predicted citations against a question's evidence set.
 *
 * A statement-level prediction hits the matching evidence statement. A
 * message-level prediction hits every evidence statement of that message.
 * A doc-level prediction hits every evidence field of that doc. Unresolved
 * predictions count against precision and hit nothing.
 */
export function scoreCitations(
  question: Question,
  citations: string[],
  truth: TruthCorpus,
): CitationScore {
  const evidence = new Map<string, EvidenceRef>();
  for (const ref of question.evidence) evidence.set(evidenceKey(ref), ref);

  const resolved = new Map<string, ResolvedCitation>();
  for (const raw of citations) {
    const c = resolveCitation(raw, truth);
    resolved.set(citationKey(c), c);
  }

  const covered = new Set<string>();
  let hits = 0;
  for (const c of resolved.values()) {
    let hit = false;
    for (const [key, ref] of evidence) {
      let match = false;
      if (isMessageEvidenceRef(ref)) {
        if (c.kind === "statement") match = c.statementId === ref.statement_id;
        else if (c.kind === "message") match = c.messageId === ref.message_id;
      } else if (c.kind === "doc") {
        match = c.docId === ref.doc_id;
      }
      if (match) {
        hit = true;
        covered.add(key);
      }
    }
    if (hit) hits += 1;
  }

  return {
    predicted: resolved.size,
    hits,
    evidenceTotal: evidence.size,
    evidenceHit: covered.size,
  };
}

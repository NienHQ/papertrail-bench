/**
 * Template-family answer extraction shared by the baselines.
 *
 * Every heuristic here is keyed off the QUESTION TEXT and the retrieved
 * chunks only. This module never sees the answer key; when no family
 * matches or nothing parses, the baseline answers null (an abstention,
 * scored 0 outside the abstention category) and cites its top hit.
 */

import type { AdapterAnswer } from "../adapter.js";
import type { Chunk } from "./substrate.js";

const DOC_ID = /\b[A-Z]{2,6}-\d{4}-\d{3,4}(?:-A\d+)?\b/;
const PO_ID = /\bPO-\d{4}-\d{4}\b/;
const PO_ID_ANY_VERSION = /\bPO-\d{4}-\d{4}(?:-A\d+)?\b/;
const MONEY = /\$[\d,]+\.\d{2}/;
const ISO_DATE = /\d{4}-\d{2}-\d{2}/;

const TERMS_STATEMENTS = [
  /payment terms of (NET\s?\d+)\b[^.]*?effective (\d{4}-\d{2}-\d{2})/gi,
  /payment terms[^.]*?are (NET\s?\d+)\s+effective (\d{4}-\d{2}-\d{2})/gi,
];

const RENT_STATEMENTS = [
  /Monthly rent is (\$[\d,]+\.\d{2})[^.]*?effective (\d{4}-\d{2}-\d{2})/gi,
  /revised to (\$[\d,]+\.\d{2})[^.]*?effective (\d{4}-\d{2}-\d{2})/gi,
];

function answered(answer: unknown, cites: string[]): AdapterAnswer {
  return { answer, citations: [...new Set(cites)] };
}

function fallback(hits: Chunk[]): AdapterAnswer {
  const top = hits[0];
  return { answer: null, citations: top === undefined ? [] : [top.messageId] };
}

/** Chunks mentioning the doc id first, then the rest, order preserved. */
function preferChunksWith(hits: Chunk[], needle: string): Chunk[] {
  const withId = hits.filter((c) => c.text.includes(needle));
  const without = hits.filter((c) => !c.text.includes(needle));
  return [...withId, ...without];
}

/** Pattern-major: the strongest pattern wins across ALL chunks before the
 * next pattern is tried, so a doc-field line beats a prose paraphrase. */
function firstMatch(chunks: Chunk[], patterns: RegExp[]): { value: string; chunk: Chunk } | null {
  for (const pattern of patterns) {
    for (const chunk of chunks) {
      const m = pattern.exec(chunk.text);
      if (m !== null) return { value: m[1] ?? m[0], chunk };
    }
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Families 1 to 3: single-document lookups                            */
/* ------------------------------------------------------------------ */

function extractDocAmount(docId: string, kind: "invoice" | "credit_note", hits: Chunk[]): AdapterAnswer {
  const chunks = preferChunksWith(hits, docId).filter((c) => c.text.includes(docId));
  const fieldLine = kind === "invoice" ? "Total:" : "Amount:";
  const hit = firstMatch(chunks, [
    new RegExp(`${fieldLine}\\s*(${MONEY.source})`),
    new RegExp(`for (${MONEY.source})`),
  ]);
  if (hit === null) return fallback(hits);
  return answered(hit.value, [hit.chunk.messageId]);
}

function extractDueDate(docId: string, hits: Chunk[]): AdapterAnswer {
  const chunks = preferChunksWith(hits, docId).filter((c) => c.text.includes(docId));
  const hit = firstMatch(chunks, [
    new RegExp(`Due date:\\s*(${ISO_DATE.source})`),
    new RegExp(`due by (${ISO_DATE.source})`),
  ]);
  if (hit === null) return fallback(hits);
  return answered(hit.value, [hit.chunk.messageId]);
}

function extractPoRef(docId: string, hits: Chunk[]): AdapterAnswer {
  const chunks = preferChunksWith(hits, docId).filter((c) => c.text.includes(docId));
  const hit = firstMatch(chunks, [
    new RegExp(`Po ref:\\s*(${PO_ID_ANY_VERSION.source})`),
    new RegExp(`against (${PO_ID_ANY_VERSION.source})`),
  ]);
  if (hit === null) return fallback(hits);
  return answered(hit.value, [hit.chunk.messageId]);
}

/* ------------------------------------------------------------------ */
/* Families 4 to 6: amendment chains                                   */
/* ------------------------------------------------------------------ */

interface VersionScan {
  /** Suffix number per version; 0 is the root. */
  versions: Map<number, { docId: string; chunks: Chunk[] }>;
}

function scanVersions(rootId: string, hits: Chunk[]): VersionScan {
  const versions = new Map<number, { docId: string; chunks: Chunk[] }>();
  const re = new RegExp(`\\b${rootId}(-A(\\d+))?\\b`, "g");
  for (const chunk of hits) {
    for (const m of chunk.text.matchAll(re)) {
      const n = m[2] === undefined ? 0 : Number(m[2]);
      const docId = m[1] === undefined ? rootId : `${rootId}${m[1]}`;
      const entry = versions.get(n);
      if (entry === undefined) versions.set(n, { docId, chunks: [chunk] });
      else if (!entry.chunks.includes(chunk)) entry.chunks.push(chunk);
    }
  }
  return { versions };
}

function extractChain(rootId: string, hits: Chunk[]): AdapterAnswer {
  const { versions } = scanVersions(rootId, hits);
  if (versions.size === 0) return fallback(hits);
  const ordered = [...versions.keys()].sort((a, b) => a - b);
  const ids = ordered.map((n) => versions.get(n)?.docId ?? rootId);
  // The chain items ARE doc ids, so cite them as docs (the resolver accepts
  // doc ids directly), plus the messages that announced the amendments.
  const cites = [...ids];
  for (const [n, entry] of versions) {
    if (n === 0) continue;
    for (const chunk of entry.chunks) cites.push(chunk.messageId);
  }
  return answered(ids, cites);
}

function extractAmendCount(rootId: string, hits: Chunk[]): AdapterAnswer {
  const { versions } = scanVersions(rootId, hits);
  if (versions.size === 0) return fallback(hits);
  const amendments = [...versions.entries()].filter(([n]) => n > 0);
  const cites: string[] = [];
  for (const [, entry] of amendments) {
    cites.push(entry.docId);
    for (const chunk of entry.chunks) cites.push(chunk.messageId);
  }
  if (amendments.length === 0) {
    const top = hits[0];
    return answered(0, top === undefined ? [] : [top.messageId]);
  }
  return answered(amendments.length, cites);
}

function extractFinalQuantity(rootId: string, hits: Chunk[]): AdapterAnswer {
  const { versions } = scanVersions(rootId, hits);
  if (versions.size === 0) return fallback(hits);
  const highest = Math.max(...versions.keys());
  const entry = versions.get(highest);
  if (entry === undefined) return fallback(hits);
  const hit = firstMatch(entry.chunks, [/Qty:\s*(\d+)/, /quantity is now (\d+)/]);
  if (hit === null) return fallback(hits);
  return answered(Number(hit.value), [entry.docId, hit.chunk.messageId]);
}

/* ------------------------------------------------------------------ */
/* Families 7 and 8: temporal supersession                             */
/* ------------------------------------------------------------------ */

interface DatedValue {
  value: string;
  effective: string;
  chunk: Chunk;
}

function collectDatedValues(chunks: Chunk[], patterns: RegExp[]): DatedValue[] {
  const out: DatedValue[] = [];
  for (const chunk of chunks) {
    for (const pattern of patterns) {
      pattern.lastIndex = 0;
      for (const m of chunk.text.matchAll(pattern)) {
        const value = m[1];
        const effective = m[2];
        if (value !== undefined && effective !== undefined) {
          out.push({ value, effective, chunk });
        }
      }
    }
  }
  return out;
}

/** Latest value with effective date at or before asOf; null when none. */
function latestAsOf(values: DatedValue[], asOf: string): DatedValue | null {
  let best: DatedValue | null = null;
  for (const v of values) {
    if (v.effective > asOf) continue;
    if (best === null || v.effective > best.effective) best = v;
  }
  return best;
}

function extractTermsAsOf(name: string, asOf: string, hits: Chunk[]): AdapterAnswer {
  const nameLower = name.toLowerCase();
  const relevant = hits.filter((c) => c.text.toLowerCase().includes(nameLower));
  const best = latestAsOf(collectDatedValues(relevant, TERMS_STATEMENTS), asOf);
  if (best === null) return fallback(hits);
  return answered(best.value.replace(/\s+/g, "").toUpperCase(), [best.chunk.messageId]);
}

function extractRentAsOf(asOf: string, hits: Chunk[]): AdapterAnswer {
  const best = latestAsOf(collectDatedValues(hits, RENT_STATEMENTS), asOf);
  if (best === null) return fallback(hits);
  return answered(best.value, [best.chunk.messageId]);
}

/* ------------------------------------------------------------------ */
/* Dispatch on question text                                           */
/* ------------------------------------------------------------------ */

export function extractAnswer(questionText: string, hits: Chunk[]): AdapterAnswer {
  const q = questionText;
  const docId = DOC_ID.exec(q)?.[0];
  const poId = PO_ID.exec(q)?.[0];

  if (/total amount of invoice/i.test(q) && docId !== undefined) {
    return extractDocAmount(docId, "invoice", hits);
  }
  if (/amount of credit note/i.test(q) && docId !== undefined) {
    return extractDocAmount(docId, "credit_note", hits);
  }
  if (/When is invoice .* due/i.test(q) && docId !== undefined) {
    return extractDueDate(docId, hits);
  }
  if (/Which purchase order does invoice/i.test(q) && docId !== undefined) {
    return extractPoRef(docId, hits);
  }
  if (/List every version of purchase order/i.test(q) && poId !== undefined) {
    return extractChain(poId, hits);
  }
  if (/How many times was purchase order .* amended/i.test(q) && poId !== undefined) {
    return extractAmendCount(poId, hits);
  }
  if (/After all amendments.*agreed quantity/i.test(q) && poId !== undefined) {
    return extractFinalQuantity(poId, hits);
  }

  const terms = /payment terms with (.+?) as of (\d{4}-\d{2}-\d{2})/i.exec(q);
  if (terms !== null && terms[1] !== undefined && terms[2] !== undefined) {
    return extractTermsAsOf(terms[1], terms[2], hits);
  }
  const rent = /monthly rent .* as of (\d{4}-\d{2}-\d{2})/i.exec(q);
  if (rent !== null && rent[1] !== undefined) {
    return extractRentAsOf(rent[1], hits);
  }

  return fallback(hits);
}

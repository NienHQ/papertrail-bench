/**
 * Shared ingest substrate for the internal baselines.
 *
 * Dependency note: better-sqlite3 (and its types) live in devDependencies on
 * purpose. The harness package is private and never published; the baselines
 * are dev-side reference systems that only run inside this repo, so a native
 * devDependency costs downstream consumers nothing.
 *
 * Everything here reads ONLY the SystemCorpus (messages/ + attachments/).
 * The answer key never enters this module.
 */

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import Database from "better-sqlite3";
import type { SystemCorpus } from "../corpus.js";

/* ------------------------------------------------------------------ */
/* Minimal RFC822 / MIME parsing                                       */
/* ------------------------------------------------------------------ */

export interface ParsedAttachment {
  filename: string;
  text: string;
}

export interface ParsedEmail {
  messageId: string;
  subject: string;
  from: string;
  date: string;
  body: string;
  attachments: ParsedAttachment[];
}

function splitHeadersBody(raw: string): { headers: string; body: string } {
  const m = /\r?\n\r?\n/.exec(raw);
  if (m === null) return { headers: raw, body: "" };
  return { headers: raw.slice(0, m.index), body: raw.slice(m.index + m[0].length) };
}

/** Unfold continuation lines, then map lowercased header name to value. */
function parseHeaders(block: string): Map<string, string> {
  const unfolded = block.replace(/\r?\n[ \t]+/g, " ");
  const headers = new Map<string, string>();
  for (const line of unfolded.split(/\r?\n/)) {
    const colon = line.indexOf(":");
    if (colon <= 0) continue;
    const name = line.slice(0, colon).trim().toLowerCase();
    if (!headers.has(name)) headers.set(name, line.slice(colon + 1).trim());
  }
  return headers;
}

function decodeQuotedPrintable(input: string): string {
  const noSoftBreaks = input.replace(/=\r?\n/g, "");
  const bytes: number[] = [];
  for (let i = 0; i < noSoftBreaks.length; i++) {
    const ch = noSoftBreaks.charCodeAt(i);
    if (noSoftBreaks[i] === "=" && /^[0-9A-Fa-f]{2}$/.test(noSoftBreaks.slice(i + 1, i + 3))) {
      bytes.push(Number.parseInt(noSoftBreaks.slice(i + 1, i + 3), 16));
      i += 2;
    } else {
      bytes.push(ch & 0xff);
    }
  }
  return Buffer.from(bytes).toString("utf8");
}

function decodeBody(content: string, transferEncoding: string): string {
  const enc = transferEncoding.trim().toLowerCase();
  if (enc === "base64") {
    return Buffer.from(content.replace(/\s+/g, ""), "base64").toString("utf8");
  }
  if (enc === "quoted-printable") return decodeQuotedPrintable(content);
  return content; // 7bit / 8bit / binary
}

function headerParam(headerValue: string, param: string): string | null {
  const re = new RegExp(`${param}\\s*=\\s*(?:"([^"]*)"|([^;\\s]+))`, "i");
  const m = re.exec(headerValue);
  if (m === null) return null;
  return m[1] ?? m[2] ?? null;
}

function stripAngles(id: string): string {
  const s = id.trim();
  return s.startsWith("<") && s.endsWith(">") ? s.slice(1, -1) : s;
}

function bareMessageId(id: string): string {
  const s = stripAngles(id);
  const at = s.indexOf("@");
  return at >= 0 ? s.slice(0, at) : s;
}

interface MimePart {
  contentType: string;
  transferEncoding: string;
  disposition: string;
  filename: string | null;
  text: string;
}

function parsePart(raw: string): MimePart {
  const { headers, body } = splitHeadersBody(raw);
  const h = parseHeaders(headers);
  const contentType = (h.get("content-type") ?? "text/plain").toLowerCase();
  const transferEncoding = h.get("content-transfer-encoding") ?? "7bit";
  const dispositionHeader = h.get("content-disposition") ?? "";
  const disposition = dispositionHeader.split(";")[0]?.trim().toLowerCase() ?? "";
  const filename = headerParam(dispositionHeader, "filename");
  const text = contentType.startsWith("text/") ? decodeBody(body, transferEncoding) : "";
  return { contentType, transferEncoding, disposition, filename, text };
}

/**
 * Parse one RFC822 message. Understands the headers the baselines need
 * (Message-ID, Subject, From, Date), single-part text bodies with 7bit,
 * quoted-printable or base64 transfer encodings, and one level of
 * multipart/* with text/* attachment parts (also decoded).
 */
export function parseEml(raw: string): ParsedEmail {
  const { headers, body } = splitHeadersBody(raw);
  const h = parseHeaders(headers);
  const messageId = bareMessageId(h.get("message-id") ?? "");
  const subject = h.get("subject") ?? "";
  const from = h.get("from") ?? "";
  const date = h.get("date") ?? "";
  const contentType = h.get("content-type") ?? "text/plain";

  if (!contentType.toLowerCase().startsWith("multipart/")) {
    const text = decodeBody(body, h.get("content-transfer-encoding") ?? "7bit");
    return { messageId, subject, from, date, body: text.trim(), attachments: [] };
  }

  const boundary = headerParam(contentType, "boundary");
  if (boundary === null) {
    return { messageId, subject, from, date, body: body.trim(), attachments: [] };
  }

  let bodyText = "";
  const attachments: ParsedAttachment[] = [];
  const sections = body.split(`--${boundary}`);
  // sections[0] is the preamble; a section starting with "--" is the epilogue.
  for (const section of sections.slice(1)) {
    if (section.startsWith("--")) break;
    const part = parsePart(section.replace(/^\r?\n/, ""));
    if (!part.contentType.startsWith("text/")) continue;
    if (part.disposition === "attachment" || part.filename !== null) {
      attachments.push({ filename: part.filename ?? "", text: part.text.trim() });
    } else if (bodyText === "") {
      bodyText = part.text.trim();
    }
  }
  return { messageId, subject, from, date, body: bodyText, attachments };
}

/* ------------------------------------------------------------------ */
/* Chunking                                                            */
/* ------------------------------------------------------------------ */

export interface Chunk {
  /** Bare message id (before the @), which the citation resolver accepts. */
  messageId: string;
  subject: string;
  source: "body" | "attachment";
  text: string;
}

const CHUNK_CAP = 1200;

/** Paragraph split, then greedy packing into chunks of at most ~1200 chars. */
export function chunkText(text: string): string[] {
  const paragraphs = text
    .split(/\r?\n\s*\r?\n/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  const chunks: string[] = [];
  let current = "";
  for (const p of paragraphs) {
    if (current.length > 0 && current.length + p.length + 2 > CHUNK_CAP) {
      chunks.push(current);
      current = "";
    }
    if (p.length > CHUNK_CAP) {
      if (current.length > 0) {
        chunks.push(current);
        current = "";
      }
      for (let i = 0; i < p.length; i += CHUNK_CAP) {
        chunks.push(p.slice(i, i + CHUNK_CAP));
      }
    } else {
      current = current.length === 0 ? p : `${current}\n\n${p}`;
    }
  }
  if (current.length > 0) chunks.push(current);
  return chunks;
}

/** Parse every .eml under messagesDir and chunk bodies plus attachments. */
export function loadChunks(corpus: SystemCorpus): Chunk[] {
  const chunks: Chunk[] = [];
  const files = readdirSync(corpus.messagesDir)
    .filter((f) => f.endsWith(".eml"))
    .sort();
  for (const file of files) {
    const parsed = parseEml(readFileSync(join(corpus.messagesDir, file), "utf8"));
    const messageId = parsed.messageId !== "" ? parsed.messageId : file.replace(/\.eml$/, "");
    for (const text of chunkText(parsed.body)) {
      chunks.push({ messageId, subject: parsed.subject, source: "body", text });
    }
    for (const att of parsed.attachments) {
      for (const text of chunkText(att.text)) {
        chunks.push({ messageId, subject: parsed.subject, source: "attachment", text });
      }
    }
  }
  return chunks;
}

/* ------------------------------------------------------------------ */
/* Tokenization                                                        */
/* ------------------------------------------------------------------ */

/** Word-ish tokens; hyphenated ids like INV-2024-0074 stay whole. */
export function tokenize(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9][a-z0-9-]*/g) ?? []).map((t) =>
    t.replace(/-+$/, ""),
  );
}

/* ------------------------------------------------------------------ */
/* BM25 (sqlite FTS5)                                                  */
/* ------------------------------------------------------------------ */

export interface RankedChunk {
  index: number;
  chunk: Chunk;
}

/**
 * English function words dropped from bm25 queries. Without this an OR
 * query drowns in "the"/"of"/"as" matches; the list is fixed (no corpus
 * statistics) so behavior is identical on every corpus.
 */
const STOPWORDS = new Set([
  "a", "after", "all", "an", "and", "are", "as", "at", "be", "by", "did",
  "do", "does", "every", "for", "from", "give", "how", "in", "is", "it",
  "its", "list", "many", "of", "on", "or", "our", "the", "times", "to",
  "was", "we", "were", "what", "when", "which", "who", "will", "with",
]);

export class Bm25Index {
  private readonly db: Database.Database;
  private readonly chunks: Chunk[];

  constructor(chunks: Chunk[]) {
    this.chunks = chunks;
    this.db = new Database(":memory:");
    this.db.exec("CREATE VIRTUAL TABLE chunks USING fts5(text, subject, tokenize='porter')");
    const insert = this.db.prepare("INSERT INTO chunks(rowid, text, subject) VALUES (?, ?, ?)");
    const tx = this.db.transaction((rows: Chunk[]) => {
      rows.forEach((c, i) => insert.run(i + 1, c.text, c.subject));
    });
    tx(chunks);
  }

  /**
   * OR of quoted, stopword-filtered question tokens, ranked by bm25 with
   * rowid tie-break. If every token is a stopword, keep them all.
   */
  search(query: string, k: number): RankedChunk[] {
    const tokens = [...new Set(tokenize(query))];
    if (tokens.length === 0) return [];
    const content = tokens.filter((t) => !STOPWORDS.has(t));
    const effective = content.length > 0 ? content : tokens;
    const match = effective.map((t) => `"${t}"`).join(" OR ");
    const rows = this.db
      .prepare("SELECT rowid FROM chunks WHERE chunks MATCH ? ORDER BY rank, rowid LIMIT ?")
      .all(match, k) as { rowid: number }[];
    return rows.flatMap((r) => {
      const chunk = this.chunks[r.rowid - 1];
      return chunk === undefined ? [] : [{ index: r.rowid - 1, chunk }];
    });
  }

  close(): void {
    this.db.close();
  }
}

/* ------------------------------------------------------------------ */
/* Naive deterministic vectors                                         */
/* ------------------------------------------------------------------ */

export const EMBED_DIMS = 64;

function fnv1a(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/**
 * Deterministic hash embedder: fnv1a bag-of-words folded into 64 dims,
 * L2 normalized. No model, no environment, fully reproducible. This is a
 * floor for what "a vector store" gives you, not an estimate of real
 * embedding models (those need an API and are out of scope here).
 */
export function embed(text: string): Float64Array {
  const vec = new Float64Array(EMBED_DIMS);
  for (const token of tokenize(text)) {
    const dim = fnv1a(token) % EMBED_DIMS;
    vec[dim] = (vec[dim] ?? 0) + 1;
  }
  let norm = 0;
  for (const v of vec) norm += v * v;
  norm = Math.sqrt(norm);
  if (norm > 0) {
    for (let i = 0; i < EMBED_DIMS; i++) vec[i] = (vec[i] ?? 0) / norm;
  }
  return vec;
}

export class VectorIndex {
  private readonly chunks: Chunk[];
  private readonly vectors: Float64Array[];

  constructor(chunks: Chunk[]) {
    this.chunks = chunks;
    this.vectors = chunks.map((c) => embed(`${c.subject}\n${c.text}`));
  }

  /** Cosine top-k with chunk-index tie-break for determinism. */
  search(query: string, k: number): RankedChunk[] {
    const q = embed(query);
    const scored = this.vectors.map((v, index) => {
      let dot = 0;
      for (let i = 0; i < EMBED_DIMS; i++) dot += (v[i] ?? 0) * (q[i] ?? 0);
      return { index, score: dot };
    });
    scored.sort((a, b) => (b.score !== a.score ? b.score - a.score : a.index - b.index));
    return scored
      .slice(0, k)
      .filter((s) => s.score > 0)
      .flatMap((s) => {
        const chunk = this.chunks[s.index];
        return chunk === undefined ? [] : [{ index: s.index, chunk }];
      });
  }
}

/* ------------------------------------------------------------------ */
/* Reciprocal rank fusion                                              */
/* ------------------------------------------------------------------ */

export const RRF_K = 60;

/** Fuse ranked lists with RRF (k=60); ties broken by chunk index. */
export function rrfFuse(lists: RankedChunk[][], k: number): RankedChunk[] {
  const scores = new Map<number, { score: number; item: RankedChunk }>();
  for (const list of lists) {
    list.forEach((item, rank) => {
      const add = 1 / (RRF_K + rank + 1);
      const existing = scores.get(item.index);
      if (existing === undefined) scores.set(item.index, { score: add, item });
      else existing.score += add;
    });
  }
  return [...scores.values()]
    .sort((a, b) =>
      b.score !== a.score ? b.score - a.score : a.item.index - b.item.index,
    )
    .slice(0, k)
    .map((s) => s.item);
}

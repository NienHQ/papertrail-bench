import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * The system-under-test view of a corpus. This is the ONLY thing the runner
 * hands to adapters: paths to the message files and the content-addressed
 * attachment store. Ground truth and questions never appear here.
 */
export interface SystemCorpus {
  readonly messagesDir: string;
  readonly attachmentsDir: string;
}

export type AnswerType =
  | "money"
  | "date"
  | "string"
  | "int"
  | "ordered_list"
  | "abstain";

export interface MoneyValue {
  amount_cents: number;
  currency: string;
}

export interface QuestionAnswer {
  type: AnswerType;
  value: unknown;
}

export interface MessageEvidenceRef {
  message_id: string;
  statement_id: string;
}

export interface DocEvidenceRef {
  doc_id: string;
  field: string;
}

export type EvidenceRef = MessageEvidenceRef | DocEvidenceRef;

export function isMessageEvidenceRef(ref: EvidenceRef): ref is MessageEvidenceRef {
  return "message_id" in ref;
}

export interface Question {
  question_id: string;
  category: number;
  template: string;
  text: string;
  answer: QuestionAnswer;
  evidence: EvidenceRef[];
  params: Record<string, unknown>;
}

export interface StatementRow {
  statement_id: string;
  message_id: string;
  occurrence: string;
  span: [number, number];
  text: string;
  targets: Record<string, string>[];
}

export interface MessageRow {
  message_id: string;
  thread_id: string;
  ts: string;
  subject: string;
  from_address: string;
  from_name: string;
  from_person: string;
  to: [string, string][];
  in_reply_to: string | null;
  references: string[];
  attachments: unknown[];
  body: string;
  statements: StatementRow[];
}

export interface DocumentRow {
  doc_id: string;
  root_id: string;
  version: number;
  kind: string;
  party_id: string;
  issued_date: string;
  supersedes: string | null;
  created_event: string;
  attachment_sha256: string;
  fields: Record<string, unknown>;
}

export interface FactRow {
  fact_id: string;
  entity: string;
  relation: string;
  value: unknown;
  valid_from: string;
  valid_to: string | null;
  source_event: string;
}

export interface PartyRow {
  party_id: string;
  name: string;
  domain: string;
  kind: string;
  is_self: boolean;
}

export interface AddressPeriod {
  address: string;
  from_date: string;
  to_date: string | null;
}

export interface PersonRow {
  person_id: string;
  party_id: string;
  name: string;
  role: string;
  addresses: AddressPeriod[];
}

export interface ThreadRow {
  thread_id: string;
  subject: string;
  participants: string[];
}

export interface Manifest {
  config: Record<string, unknown>;
  counts: Record<string, number>;
  files: Record<string, string>;
  [key: string]: unknown;
}

/**
 * The scorer's view: everything, including ground truth and questions.
 * Only the runner and the oracle adapter ever touch this.
 */
export interface TruthCorpus {
  corpusDir: string;
  manifest: Manifest;
  questions: Question[];
  messages: Map<string, MessageRow>;
  statements: Map<string, StatementRow>;
  documents: Map<string, DocumentRow>;
  facts: FactRow[];
  parties: PartyRow[];
  people: PersonRow[];
  threads: ThreadRow[];
}

/**
 * Build the adapter-facing view of a corpus. Constructed with exactly two
 * keys by design; tests assert nothing else can leak through this object.
 */
export function loadSystemCorpus(corpusDir: string): SystemCorpus {
  return {
    messagesDir: join(corpusDir, "messages"),
    attachmentsDir: join(corpusDir, "attachments"),
  };
}

function readJsonl<T>(path: string): T[] {
  const raw = readFileSync(path, "utf8");
  const rows: T[] = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.length > 0) rows.push(JSON.parse(trimmed) as T);
  }
  return rows;
}

export function loadTruthCorpus(corpusDir: string): TruthCorpus {
  const gt = join(corpusDir, "ground_truth");
  const manifest = JSON.parse(
    readFileSync(join(corpusDir, "manifest.json"), "utf8"),
  ) as Manifest;
  const questions = readJsonl<Question>(join(corpusDir, "questions.jsonl"));
  const messageRows = readJsonl<MessageRow>(join(gt, "messages.jsonl"));
  const documentRows = readJsonl<DocumentRow>(join(gt, "documents.jsonl"));
  const evidenceRows = readJsonl<StatementRow>(join(gt, "evidence.jsonl"));
  const facts = readJsonl<FactRow>(join(gt, "facts.jsonl"));
  const parties = readJsonl<PartyRow>(join(gt, "parties.jsonl"));
  const people = readJsonl<PersonRow>(join(gt, "people.jsonl"));
  const threads = readJsonl<ThreadRow>(join(gt, "threads.jsonl"));

  const messages = new Map<string, MessageRow>();
  for (const m of messageRows) messages.set(m.message_id, m);

  const statements = new Map<string, StatementRow>();
  for (const s of evidenceRows) statements.set(s.statement_id, s);
  for (const m of messageRows) {
    for (const s of m.statements) {
      if (!statements.has(s.statement_id)) statements.set(s.statement_id, s);
    }
  }

  const documents = new Map<string, DocumentRow>();
  for (const d of documentRows) documents.set(d.doc_id, d);

  return {
    corpusDir,
    manifest,
    questions,
    messages,
    statements,
    documents,
    facts,
    parties,
    people,
    threads,
  };
}

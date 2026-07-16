import { describe, expect, it } from "vitest";
import type {
  DocumentRow,
  MessageRow,
  Question,
  StatementRow,
  TruthCorpus,
} from "../src/corpus.js";
import {
  isAbstention,
  lcsLength,
  parseDate,
  parseInteger,
  parseMoney,
  resolveCitation,
  scoreAnswer,
  scoreCitations,
  scoreDate,
  scoreInt,
  scoreMoney,
  scoreOrderedList,
  scoreString,
} from "../src/score.js";

/* ------------------------------------------------------------------ */
/* money                                                               */
/* ------------------------------------------------------------------ */

describe("money", () => {
  const expected = { amount_cents: 125000, currency: "USD" };

  it("parses symbol form", () => {
    expect(parseMoney("$1,250.00")).toEqual({ amountCents: 125000, currency: "USD" });
  });

  it("parses trailing code form", () => {
    expect(parseMoney("1250 USD")).toEqual({ amountCents: 125000, currency: "USD" });
  });

  it("parses leading code form", () => {
    expect(parseMoney("USD 1,250")).toEqual({ amountCents: 125000, currency: "USD" });
  });

  it("parses plain numbers as major units with no currency", () => {
    expect(parseMoney(1250)).toEqual({ amountCents: 125000, currency: null });
  });

  it("parses the schema object shape", () => {
    expect(parseMoney({ amount_cents: 125000, currency: "usd" })).toEqual({
      amountCents: 125000,
      currency: "USD",
    });
  });

  it("parses single-digit cents padding", () => {
    expect(parseMoney("$12.5")).toEqual({ amountCents: 1250, currency: "USD" });
  });

  it("parses negative amounts", () => {
    expect(parseMoney("-$5.00")).toEqual({ amountCents: -500, currency: "USD" });
  });

  it("rejects three decimal places and junk", () => {
    expect(parseMoney("1250.123")).toBeNull();
    expect(parseMoney("about 1250")).toBeNull();
    expect(parseMoney(Number.NaN)).toBeNull();
    expect(parseMoney([1250])).toBeNull();
  });

  it("scores all accepted forms as exact matches", () => {
    for (const form of ["$1,250.00", "1250 USD", "USD 1,250", "1,250.00 USD", 1250]) {
      expect(scoreMoney(expected, form)).toBe(1);
    }
  });

  it("scores wrong amount and wrong currency as 0", () => {
    expect(scoreMoney(expected, "$1,250.01")).toBe(0);
    expect(scoreMoney(expected, "EUR 1,250")).toBe(0);
    expect(scoreMoney(expected, null)).toBe(0);
  });
});

/* ------------------------------------------------------------------ */
/* date                                                                */
/* ------------------------------------------------------------------ */

describe("date", () => {
  it("accepts ISO and ISO with a time suffix", () => {
    expect(parseDate("2024-02-06")).toBe("2024-02-06");
    expect(parseDate("2024-02-06T00:00:00Z")).toBe("2024-02-06");
  });

  it("accepts month-name forms", () => {
    expect(parseDate("Feb 6, 2024")).toBe("2024-02-06");
    expect(parseDate("February 6 2024")).toBe("2024-02-06");
    expect(parseDate("6 Feb 2024")).toBe("2024-02-06");
    expect(parseDate("Sept 3rd, 2024")).toBe("2024-09-03");
  });

  it("rejects ambiguous numeric slash forms", () => {
    expect(parseDate("06/02/2024")).toBeNull();
    expect(parseDate("2024/02/06")).toBeNull();
  });

  it("rejects invalid months, unknown month names, non-strings", () => {
    expect(parseDate("2024-13-01")).toBeNull();
    expect(parseDate("Foo 6, 2024")).toBeNull();
    expect(parseDate(20240206)).toBeNull();
  });

  it("scores exact after normalization", () => {
    expect(scoreDate("2024-03-10", "Mar 10, 2024")).toBe(1);
    expect(scoreDate("2024-03-10", "2024-03-11")).toBe(0);
  });
});

/* ------------------------------------------------------------------ */
/* string / int                                                        */
/* ------------------------------------------------------------------ */

describe("string", () => {
  it("is exact after trim, case fold, and whitespace collapse", () => {
    expect(scoreString("NET30", "  net30 ")).toBe(1);
    expect(scoreString("NET 30", "net   30")).toBe(1);
    expect(scoreString("NET30", "NET 30")).toBe(0);
    expect(scoreString("PO-2024-0020", "po-2024-0020")).toBe(1);
    expect(scoreString("NET30", null)).toBe(0);
  });
});

describe("int", () => {
  it("coerces digit strings and comma grouping", () => {
    expect(parseInteger(3)).toBe(3);
    expect(parseInteger("3")).toBe(3);
    expect(parseInteger("1,250")).toBe(1250);
    expect(parseInteger("-7")).toBe(-7);
  });

  it("rejects non-integers", () => {
    expect(parseInteger(3.5)).toBeNull();
    expect(parseInteger("3.0")).toBeNull();
    expect(parseInteger("three")).toBeNull();
    expect(parseInteger(null)).toBeNull();
  });

  it("scores exact equality", () => {
    expect(scoreInt(3, "3")).toBe(1);
    expect(scoreInt(3, 4)).toBe(0);
  });
});

/* ------------------------------------------------------------------ */
/* ordered_list                                                        */
/* ------------------------------------------------------------------ */

describe("ordered_list", () => {
  const chain = ["PO-2024-0047", "PO-2024-0047-A1", "PO-2024-0047-A2"];

  it("exact sequence scores 1.0, case-insensitively", () => {
    expect(scoreOrderedList(chain, chain)).toBe(1);
    expect(scoreOrderedList(chain, chain.map((s) => s.toLowerCase()))).toBe(1);
  });

  it("chain of 3 with one item missing scores 2/3", () => {
    expect(scoreOrderedList(chain, ["PO-2024-0047", "PO-2024-0047-A2"])).toBeCloseTo(2 / 3);
  });

  it("wrong order gets LCS credit only", () => {
    expect(scoreOrderedList(["A", "B"], ["B", "A"])).toBe(0.5);
  });

  it("accepts a comma-separated string form", () => {
    expect(scoreOrderedList(chain, chain.join(", "))).toBe(1);
  });

  it("rejects non-lists", () => {
    expect(scoreOrderedList(chain, 42)).toBe(0);
    expect(scoreOrderedList(chain, null)).toBe(0);
  });

  it("lcsLength is a plain LCS", () => {
    expect(lcsLength(["a", "b", "c"], ["a", "c"])).toBe(2);
    expect(lcsLength(["a", "b"], ["x", "y"])).toBe(0);
    expect(lcsLength([], ["a"])).toBe(0);
  });
});

/* ------------------------------------------------------------------ */
/* abstention                                                          */
/* ------------------------------------------------------------------ */

describe("abstention", () => {
  it("accepts the documented refusal shapes", () => {
    expect(isAbstention(null)).toBe(true);
    expect(isAbstention(undefined)).toBe(true);
    expect(isAbstention("")).toBe(true);
    expect(isAbstention("ABSTAIN.")).toBe(true);
    expect(isAbstention("I don't know")).toBe(true);
    expect(isAbstention("no  answer")).toBe(true);
    expect(isAbstention({ abstain: true })).toBe(true);
  });

  it("rejects substantive answers", () => {
    expect(isAbstention("NET30")).toBe(false);
    expect(isAbstention(0)).toBe(false);
    expect(isAbstention(["abstain"])).toBe(false);
  });

  it("dispatches through scoreAnswer", () => {
    expect(scoreAnswer({ type: "abstain", value: null }, null)).toBe(1);
    expect(scoreAnswer({ type: "abstain", value: null }, "$5.00")).toBe(0);
    expect(scoreAnswer({ type: "string", value: "NET30" }, "abstain")).toBe(0);
  });
});

/* ------------------------------------------------------------------ */
/* citations                                                           */
/* ------------------------------------------------------------------ */

function makeTruth(): TruthCorpus {
  const statements: StatementRow[] = [
    {
      statement_id: "MSG-000012-S1",
      message_id: "MSG-000012",
      occurrence: "canonical",
      span: [0, 10],
      text: "s1",
      targets: [],
    },
    {
      statement_id: "MSG-000012-S2",
      message_id: "MSG-000012",
      occurrence: "canonical",
      span: [11, 20],
      text: "s2",
      targets: [],
    },
    {
      statement_id: "MSG-000099-S1",
      message_id: "MSG-000099",
      occurrence: "canonical",
      span: [0, 5],
      text: "other",
      targets: [],
    },
  ];
  const message = (id: string): MessageRow => ({
    message_id: id,
    thread_id: "THR-0001",
    ts: "2024-01-02T09:00:00+00:00",
    subject: "s",
    from_address: "a@x.example",
    from_name: "A",
    from_person: "PER-0001",
    to: [],
    in_reply_to: null,
    references: [],
    attachments: [],
    body: "",
    statements: statements.filter((s) => s.message_id === id),
  });
  const doc: DocumentRow = {
    doc_id: "INV-2024-0007",
    root_id: "INV-2024-0007",
    version: 1,
    kind: "invoice",
    party_id: "PTY-0001",
    issued_date: "2024-01-05",
    supersedes: null,
    created_event: "EVT-000001",
    attachment_sha256: "0".repeat(64),
    fields: { total_cents: 100, due_date: "2024-02-04" },
  };
  return {
    corpusDir: "/nonexistent",
    manifest: { config: {}, counts: {}, files: {} },
    questions: [],
    messages: new Map([
      ["MSG-000012", message("MSG-000012")],
      ["MSG-000099", message("MSG-000099")],
    ]),
    statements: new Map(statements.map((s) => [s.statement_id, s])),
    documents: new Map([[doc.doc_id, doc]]),
    facts: [],
    parties: [],
    people: [],
    threads: [],
  };
}

describe("resolveCitation", () => {
  const truth = makeTruth();

  it("resolves a bare message id", () => {
    expect(resolveCitation("MSG-000012", truth)).toEqual({
      kind: "message",
      messageId: "MSG-000012",
    });
  });

  it("resolves a message id with a domain part", () => {
    expect(resolveCitation("MSG-000012@x.example", truth)).toEqual({
      kind: "message",
      messageId: "MSG-000012",
    });
  });

  it("resolves an angle-bracketed Message-ID header", () => {
    expect(resolveCitation("<MSG-000012@x.example>", truth)).toEqual({
      kind: "message",
      messageId: "MSG-000012",
    });
  });

  it("resolves messageId:statementId", () => {
    expect(resolveCitation("MSG-000012:MSG-000012-S1", truth)).toEqual({
      kind: "statement",
      statementId: "MSG-000012-S1",
      messageId: "MSG-000012",
    });
  });

  it("resolves messageId with domain plus statementId", () => {
    expect(resolveCitation("MSG-000012@x.example:MSG-000012-S2", truth)).toEqual({
      kind: "statement",
      statementId: "MSG-000012-S2",
      messageId: "MSG-000012",
    });
  });

  it("resolves a bare statement id", () => {
    expect(resolveCitation("MSG-000012-S1", truth)).toEqual({
      kind: "statement",
      statementId: "MSG-000012-S1",
      messageId: "MSG-000012",
    });
  });

  it("resolves a doc id", () => {
    expect(resolveCitation("INV-2024-0007", truth)).toEqual({
      kind: "doc",
      docId: "INV-2024-0007",
    });
  });

  it("falls back to message level for an unknown statement of a known message", () => {
    expect(resolveCitation("MSG-000012:MSG-000012-S9", truth)).toEqual({
      kind: "message",
      messageId: "MSG-000012",
    });
  });

  it("marks everything else unresolved", () => {
    expect(resolveCitation("BOGUS-1", truth)).toEqual({ kind: "unresolved", raw: "BOGUS-1" });
  });
});

describe("scoreCitations", () => {
  const truth = makeTruth();
  const question: Question = {
    question_id: "Q-TEST",
    category: 1,
    template: "t",
    text: "?",
    answer: { type: "string", value: "x" },
    evidence: [
      { message_id: "MSG-000012", statement_id: "MSG-000012-S1" },
      { message_id: "MSG-000012", statement_id: "MSG-000012-S2" },
      { doc_id: "INV-2024-0007", field: "total_cents" },
    ],
    params: {},
  };

  it("statement-level prediction hits exactly its statement", () => {
    const s = scoreCitations(question, ["MSG-000012:MSG-000012-S1"], truth);
    expect(s).toEqual({ predicted: 1, hits: 1, evidenceTotal: 3, evidenceHit: 1 });
  });

  it("message-level prediction hits all evidence statements of the message", () => {
    const s = scoreCitations(question, ["MSG-000012", "BOGUS-1"], truth);
    expect(s).toEqual({ predicted: 2, hits: 1, evidenceTotal: 3, evidenceHit: 2 });
  });

  it("doc prediction hits every evidence field of the doc", () => {
    const twoFields: Question = {
      ...question,
      evidence: [
        { doc_id: "INV-2024-0007", field: "total_cents" },
        { doc_id: "INV-2024-0007", field: "due_date" },
      ],
    };
    const s = scoreCitations(twoFields, ["INV-2024-0007"], truth);
    expect(s).toEqual({ predicted: 1, hits: 1, evidenceTotal: 2, evidenceHit: 2 });
  });

  it("citing a resolvable but non-evidence message costs precision", () => {
    const s = scoreCitations(question, ["MSG-000012-S1", "MSG-000099"], truth);
    expect(s).toEqual({ predicted: 2, hits: 1, evidenceTotal: 3, evidenceHit: 1 });
  });

  it("duplicate predictions are deduplicated before scoring", () => {
    const s = scoreCitations(
      question,
      ["MSG-000012:MSG-000012-S1", "MSG-000012-S1", "<MSG-000012-S1>"],
      truth,
    );
    expect(s).toEqual({ predicted: 1, hits: 1, evidenceTotal: 3, evidenceHit: 1 });
  });

  it("no predictions means zero hits and untouched evidence", () => {
    const s = scoreCitations(question, [], truth);
    expect(s).toEqual({ predicted: 0, hits: 0, evidenceTotal: 3, evidenceHit: 0 });
  });
});

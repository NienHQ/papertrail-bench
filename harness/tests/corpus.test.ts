import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { loadSystemCorpus, loadTruthCorpus } from "../src/corpus.js";

const FIXTURE = join(fileURLToPath(new URL(".", import.meta.url)), "fixtures", "corpus-h1");

describe("loadSystemCorpus", () => {
  it("exposes only the messages and attachments paths (leaky adapter guard)", () => {
    const system = loadSystemCorpus(FIXTURE);
    expect(Object.keys(system).sort()).toEqual(["attachmentsDir", "messagesDir"]);
    expect(system.messagesDir).toBe(join(FIXTURE, "messages"));
    expect(system.attachmentsDir).toBe(join(FIXTURE, "attachments"));
    const serialized = JSON.stringify(system);
    expect(serialized).not.toContain("ground_truth");
    expect(serialized).not.toContain("questions");
    expect(serialized).not.toContain("manifest");
  });
});

describe("loadTruthCorpus", () => {
  it("loads every table with counts matching the manifest", () => {
    const truth = loadTruthCorpus(FIXTURE);
    const counts = truth.manifest.counts;
    expect(truth.messages.size).toBe(counts["messages"]);
    expect(truth.documents.size).toBe(counts["documents"]);
    expect(truth.questions.length).toBe(counts["questions"]);
    expect(truth.facts.length).toBe(counts["facts"]);
    expect(truth.parties.length).toBe(counts["parties"]);
    expect(truth.people.length).toBe(counts["people"]);
    expect(truth.threads.length).toBe(counts["threads"]);
    expect(truth.statements.size).toBeGreaterThan(0);
  });

  it("indexes statements by id with a message back-reference", () => {
    const truth = loadTruthCorpus(FIXTURE);
    const statement = truth.statements.get("MSG-000001-S1");
    expect(statement).toBeDefined();
    expect(statement?.message_id).toBe("MSG-000001");
  });

  it("only fixture categories 1 to 3 are present", () => {
    const truth = loadTruthCorpus(FIXTURE);
    const categories = new Set(truth.questions.map((q) => q.category));
    expect([...categories].sort()).toEqual([1, 2, 3]);
  });
});

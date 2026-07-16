import type { ChildProcess } from "node:child_process";
import { spawn } from "node:child_process";
import { dirname } from "node:path";
import type { Adapter, AdapterAnswer, AdapterQuestion } from "./adapter.js";
import type { SystemCorpus } from "./corpus.js";
import { DEFAULT_INGEST_TIMEOUT_MS, DEFAULT_QUESTION_TIMEOUT_MS } from "./run.js";

export const PROTOCOL_VERSION = "papertrail-protocol v1";

const SHUTDOWN_GRACE_MS = 2_000;

export interface SubprocessOptions {
  name?: string;
  ingestTimeoutMs?: number;
  questionTimeoutMs?: number;
}

interface Pending {
  resolve: (msg: Record<string, unknown>) => void;
  reject: (err: Error) => void;
  timer: NodeJS.Timeout;
}

function truncate(s: string, max = 120): string {
  return s.length > max ? `${s.slice(0, max)}...` : s;
}

/**
 * Runs a system under test as a child process speaking the newline-delimited
 * JSON protocol documented in PROTOCOL.md. One JSON object per line on
 * stdin (runner to adapter) and stdout (adapter to runner); stderr passes
 * through untouched. Timeouts and unparseable lines reject the pending
 * question, which the runner records as a 0 with a note.
 */
export class SubprocessAdapter implements Adapter {
  readonly name: string;
  private readonly command: string;
  private readonly ingestTimeoutMs: number;
  private readonly questionTimeoutMs: number;
  private child: ChildProcess | null = null;
  private buffer = "";
  /** Pending replies keyed by question id; "" is the ingest/ready slot. */
  private readonly pending = new Map<string, Pending>();
  private exitError: Error | null = null;

  constructor(command: string, options: SubprocessOptions = {}) {
    this.command = command;
    this.name = options.name ?? `subprocess(${command})`;
    this.ingestTimeoutMs = options.ingestTimeoutMs ?? DEFAULT_INGEST_TIMEOUT_MS;
    this.questionTimeoutMs = options.questionTimeoutMs ?? DEFAULT_QUESTION_TIMEOUT_MS;
  }

  async ingest(corpus: SystemCorpus): Promise<void> {
    const child = spawn(this.command, {
      shell: true,
      stdio: ["pipe", "pipe", "inherit"],
    });
    this.child = child;
    child.stdout?.setEncoding("utf8");
    child.stdout?.on("data", (chunk: string) => {
      this.onData(chunk);
    });
    child.on("error", (err) => {
      this.failAll(new Error(`adapter process failed to start: ${err.message}`));
    });
    child.on("exit", (code, signal) => {
      this.exitError = new Error(
        `adapter process exited (code ${String(code)}, signal ${String(signal)})`,
      );
      this.failAll(this.exitError);
    });

    this.send({
      type: "ingest",
      protocol: PROTOCOL_VERSION,
      corpusDir: dirname(corpus.messagesDir),
      messagesDir: corpus.messagesDir,
      attachmentsDir: corpus.attachmentsDir,
    });
    const reply = await this.waitFor("", this.ingestTimeoutMs, "ingest");
    if (reply["type"] !== "ready") {
      throw new Error(`expected {type:"ready"}, got: ${truncate(JSON.stringify(reply))}`);
    }
  }

  async answer(q: AdapterQuestion): Promise<AdapterAnswer> {
    this.send({ type: "question", id: q.id, category: q.category, text: q.text });
    const reply = await this.waitFor(q.id, this.questionTimeoutMs, q.id);
    const citations = Array.isArray(reply["citations"])
      ? reply["citations"].filter((c): c is string => typeof c === "string")
      : [];
    return { answer: reply["answer"] ?? null, citations };
  }

  async close(): Promise<void> {
    const child = this.child;
    if (child === null) return;
    this.child = null;
    if (child.exitCode === null && child.signalCode === null) {
      try {
        child.stdin?.write(`${JSON.stringify({ type: "shutdown" })}\n`);
      } catch {
        // already gone
      }
      await new Promise<void>((resolve) => {
        const timer = setTimeout(() => {
          child.kill("SIGKILL");
          resolve();
        }, SHUTDOWN_GRACE_MS);
        child.once("exit", () => {
          clearTimeout(timer);
          resolve();
        });
      });
    }
  }

  private send(message: Record<string, unknown>): void {
    if (this.exitError !== null) throw this.exitError;
    const child = this.child;
    if (child === null || child.stdin === null) {
      throw new Error("adapter process is not running");
    }
    child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  private waitFor(
    id: string,
    timeoutMs: number,
    label: string,
  ): Promise<Record<string, unknown>> {
    return new Promise<Record<string, unknown>>((resolve, reject) => {
      if (this.exitError !== null) {
        reject(this.exitError);
        return;
      }
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`timeout after ${String(timeoutMs)} ms (${label})`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
    });
  }

  private onData(chunk: string): void {
    this.buffer += chunk;
    for (;;) {
      const nl = this.buffer.indexOf("\n");
      if (nl < 0) break;
      const line = this.buffer.slice(0, nl).trim();
      this.buffer = this.buffer.slice(nl + 1);
      if (line.length > 0) this.onLine(line);
    }
  }

  private onLine(line: string): void {
    let msg: unknown;
    try {
      msg = JSON.parse(line);
    } catch {
      this.rejectOldest(new Error(`bad JSON from adapter: ${truncate(line)}`));
      return;
    }
    if (typeof msg !== "object" || msg === null || Array.isArray(msg)) {
      this.rejectOldest(new Error(`bad message from adapter: ${truncate(line)}`));
      return;
    }
    const message = msg as Record<string, unknown>;
    if (message["type"] === "ready") {
      this.settle("", message);
      return;
    }
    if (message["type"] === "answer" && typeof message["id"] === "string") {
      // A reply for a question that already timed out finds no pending
      // entry and is discarded silently.
      this.settle(message["id"], message);
      return;
    }
    this.rejectOldest(new Error(`unexpected message from adapter: ${truncate(line)}`));
  }

  private settle(id: string, message: Record<string, unknown>): void {
    const entry = this.pending.get(id);
    if (entry === undefined) return;
    this.pending.delete(id);
    clearTimeout(entry.timer);
    entry.resolve(message);
  }

  private rejectOldest(err: Error): void {
    const first = this.pending.entries().next();
    if (first.done === true) return;
    const [id, entry] = first.value;
    this.pending.delete(id);
    clearTimeout(entry.timer);
    entry.reject(err);
  }

  private failAll(err: Error): void {
    for (const [, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(err);
    }
    this.pending.clear();
  }
}

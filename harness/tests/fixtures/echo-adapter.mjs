// Minimal subprocess adapter used by the protocol round-trip test.
// Speaks papertrail-protocol v1 on stdin/stdout. Behavior by question id:
//   Q-0001: correct answer with correct citations
//   Q-0002: emits a non-JSON line (protocol violation)
//   Q-0003: never replies (forces a timeout)
//   others: garbage answer with an unresolvable citation
import { createInterface } from "node:readline";

const KNOWN = {
  "Q-0001": {
    answer: "$12,322.50",
    citations: ["INV-2024-0074", "MSG-000291:MSG-000291-S1"],
  },
};

function emit(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
}

const rl = createInterface({ input: process.stdin });
rl.on("line", (line) => {
  const msg = JSON.parse(line);
  if (msg.type === "ingest") {
    process.stderr.write(`echo-adapter: ingest ${msg.protocol}\n`);
    emit({ type: "ready" });
    return;
  }
  if (msg.type === "question") {
    if (msg.id === "Q-0002") {
      process.stdout.write("this is not json\n");
      return;
    }
    if (msg.id === "Q-0003") {
      return;
    }
    const known = KNOWN[msg.id];
    if (known) {
      emit({ type: "answer", id: msg.id, ...known });
    } else {
      emit({ type: "answer", id: msg.id, answer: "garbage", citations: ["BOGUS-999"] });
    }
    return;
  }
  if (msg.type === "shutdown") {
    process.exit(0);
  }
});

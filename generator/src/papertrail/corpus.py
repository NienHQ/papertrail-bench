"""Corpus assembly and on-disk layout (schema doc section 8)."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

from . import GENERATOR_VERSION
from .facts import derive_facts
from .model import to_row
from .questions import generate_questions
from .render import render, render_attachment, render_eml
from .simulate import Config, SimResult, simulate


@dataclasses.dataclass
class Corpus:
    sim: SimResult
    facts: list
    render_result: "object"
    questions: list


def build(cfg: Config) -> Corpus:
    sim = simulate(cfg)
    facts, event_fact = derive_facts(sim.events, sim.world.self_party.party_id)
    rr = render(sim, event_fact)
    questions = generate_questions(sim, facts, rr)
    return Corpus(sim=sim, facts=facts, render_result=rr, questions=questions)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="ascii") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def write(corpus: Corpus, out: Path) -> dict:
    sim, rr = corpus.sim, corpus.render_result
    world = sim.world
    docs_by_id = {d.doc_id: d for d in sim.documents}

    (out / "messages").mkdir(parents=True, exist_ok=True)
    (out / "attachments").mkdir(exist_ok=True)
    gt = out / "ground_truth"
    gt.mkdir(exist_ok=True)

    attachment_hash: dict[str, str] = {}
    for doc in sim.documents:
        blob = render_attachment(doc, world)
        h = hashlib.sha256(blob).hexdigest()
        attachment_hash[doc.doc_id] = h
        (out / "attachments" / h).write_bytes(blob)

    for msg in rr.messages:
        (out / "messages" / f"{msg.message_id}.eml").write_bytes(
            render_eml(msg, world, docs_by_id))

    _write_jsonl(gt / "parties.jsonl", [to_row(p) for p in world.parties])
    _write_jsonl(gt / "people.jsonl", [to_row(p) for p in world.people])
    _write_jsonl(gt / "events.jsonl", [to_row(e) for e in sim.events])
    _write_jsonl(gt / "documents.jsonl",
                 [{**to_row(d), "attachment_sha256": attachment_hash[d.doc_id]}
                  for d in sim.documents])
    _write_jsonl(gt / "facts.jsonl", [to_row(f) for f in corpus.facts])
    _write_jsonl(gt / "threads.jsonl", [to_row(t) for t in rr.threads])
    _write_jsonl(gt / "messages.jsonl", [to_row(m) for m in rr.messages])
    evidence_rows = []
    for m in rr.messages:
        for s in m.statements:
            evidence_rows.append(to_row(s))
    _write_jsonl(gt / "evidence.jsonl", evidence_rows)
    _write_jsonl(out / "questions.jsonl", [to_row(q) for q in corpus.questions])

    files = sorted(p for p in out.rglob("*")
                   if p.is_file() and p.name != "manifest.json")
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": sim.config.seed,
        "config": dataclasses.asdict(sim.config),
        "counts": {
            "parties": len(world.parties), "people": len(world.people),
            "events": len(sim.events), "documents": len(sim.documents),
            "facts": len(corpus.facts), "threads": len(rr.threads),
            "messages": len(rr.messages),
            "questions": len(corpus.questions),
        },
        "files": {str(p.relative_to(out)):
                  hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest

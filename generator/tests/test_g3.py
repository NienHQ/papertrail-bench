"""G3 realism screws: flags-off byte identity plus one focused test per
screw. The hard-preset corpus additionally runs through every invariant
test via the parametrized ``corpus`` fixture in conftest."""
import dataclasses
import hashlib
import json
import re
from datetime import timedelta

from papertrail.cli import main as cli_main
from papertrail.corpus import build, write
from papertrail.render import render_attachment
from papertrail.simulate import HARD_PRESET, Config

from conftest import CFG, HARD_CFG

# sha256 of manifest.json for `generate --seed 42` (default config, all
# screws off), recorded from pre-G3 generator output. The whole corpus is
# covered: the manifest embeds every file's hash.
SEED42_MANIFEST_SHA256 = \
    "8aa46286219b56be6aae677d3fae9b404c1673068133f5ddf4660c79c3d129c7"

MONEY_FORMS = [
    re.compile(r"\$[\d,]+\.\d{2}"),           # $1,250.00
    re.compile(r"\b[\d.]+ USD\b"),            # 1250 USD / 1250.50 USD
    re.compile(r"\bUSD [\d,]+\.\d{2}"),       # USD 1,250.00
]


def _by_thread(rr):
    threads = {}
    for m in rr.messages:  # already sorted by (ts, message_id)
        threads.setdefault(m.thread_id, []).append(m)
    return threads


def test_flags_off_seed42_manifest_byte_identical(tmp_path):
    """The G3 screws consume zero rng draws when off: the default seed-42
    corpus is byte-identical with pre-G3 generator output."""
    manifest = write(build(Config()), tmp_path / "c")
    raw = (tmp_path / "c" / "manifest.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SEED42_MANIFEST_SHA256
    for screw in HARD_PRESET:
        assert screw not in manifest["config"]  # omitted when off


def test_truncate_references():
    tr = build(dataclasses.replace(CFG, truncate_references=True))
    clean = build(CFG)
    # the screw is render-header-only: same messages, same bodies
    assert [m.message_id for m in tr.render_result.messages] == \
        [m.message_id for m in clean.render_result.messages]
    assert [m.body for m in tr.render_result.messages] == \
        [m.body for m in clean.render_result.messages]
    dropped = 0
    for msgs in _by_thread(tr.render_result).values():
        for i, m in enumerate(msgs):  # i == reply index; root is 0
            assert len(m.references) <= 2
            if i == 0:
                continue
            if i % 5 == 0:  # every 5th reply: subject-only continuation
                dropped += 1
                assert m.in_reply_to is None and m.references == []
                assert m.subject.startswith("Re: ")
            else:
                assert m.in_reply_to is not None
                assert m.references[-1] is not None
    assert dropped > 0, "no thread long enough to exercise the drop"


def test_quoted_replies_spans_targets_and_canonical_only_index():
    qc = build(dataclasses.replace(CFG, quoted_replies=True))
    rr = qc.render_result
    occ_by_sid = {s.statement_id: s
                  for m in rr.messages for s in m.statements}
    quoted_total = 0
    for msgs in _by_thread(rr).values():
        for prev, m in zip(msgs, msgs[1:]):
            assert f"On {prev.ts.date().isoformat()}, " \
                   f"{prev.from_name} wrote:" in m.body
            quoted = [s for s in m.statements if s.occurrence == "quoted"]
            quoted_total += len(quoted)
            # one quoted occurrence per statement of the quoted message,
            # same text, same targets, span valid inside the "> " block
            assert [s.text for s in quoted] == \
                [s.text for s in prev.statements]
            for q, orig in zip(quoted, prev.statements):
                start, end = q.span
                assert m.body[start:end] == q.text == orig.text
                assert q.targets == orig.targets
                assert m.body[start - 2:start].endswith("> ") or \
                    "> " in m.body[m.body.rfind("\n", 0, start) + 1:start]
    assert quoted_total > 0
    # the question evidence index stays canonical-only
    for occs in rr.evidence_index.values():
        for _, sid in occs:
            assert occ_by_sid[sid].occurrence == "canonical"
    for q in qc.questions:
        for ref in q.evidence:
            if "statement_id" in ref:
                assert occ_by_sid[ref["statement_id"]].occurrence == \
                    "canonical"


def test_near_dup_invoices():
    nd = build(dataclasses.replace(CFG, near_dup_invoices=0.5))
    docs = {d.doc_id: d for d in nd.sim.documents}
    dups = [d for d in nd.sim.documents
            if d.fields.get("voided_by_correction")]
    assert dups, "raise near_dup_invoices; no duplicates drawn"
    corrections = {e.payload["duplicate_ref"]: e for e in nd.sim.events
                   if e.type == "INVOICE_CORRECTED"}
    paid_refs = {e.payload["invoice_ref"] for e in nd.sim.events
                 if e.type in ("PAYMENT_SENT", "PAYMENT_RECEIVED")}
    for dup in dups:
        orig = docs[dup.fields["duplicate_of"]]
        # verbatim re-issue one day later under the next invoice number
        same = {k: v for k, v in dup.fields.items()
                if k not in ("invoice_number", "duplicate_of",
                             "voided_by_correction")}
        assert same == {k: v for k, v in orig.fields.items()
                        if k != "invoice_number"}
        assert dup.issued_date == orig.issued_date + timedelta(days=1)
        assert int(dup.doc_id.rsplit("-", 1)[1]) > \
            int(orig.doc_id.rsplit("-", 1)[1])
        # voided by a rendered correction on the same thread
        corr = corrections[dup.doc_id]
        assert corr.payload["original_ref"] == orig.doc_id
        occs = nd.render_result.evidence_index[("event", corr.event_id)]
        assert len(occs) == 1
        # payments ignore duplicates
        assert dup.doc_id not in paid_refs
        assert orig.doc_id in paid_refs
        # the rendered duplicate attachment does not leak ground truth
        blob = render_attachment(dup, nd.sim.world).decode("ascii")
        assert "Duplicate of" not in blob
        assert "Voided" not in blob
    # samplers never touch voided invoices; abstention ids clear the
    # extra consumed numbers
    dup_ids = {d.doc_id for d in dups}
    issued_max = max(int(d.doc_id.rsplit("-", 1)[1])
                     for d in nd.sim.documents
                     if d.kind == "invoice")
    for q in nd.questions:
        assert not dup_ids & set(str(v) for v in q.params.values())
        if q.answer["type"] == "ordered_list":
            assert not dup_ids & set(q.answer["value"])
        if q.template == "nonexistent_invoice_total":
            assert int(q.params["missing_id"].rsplit("-", 1)[1]) > issued_max


def test_format_drift():
    fd = build(dataclasses.replace(CFG, format_drift=True))
    clean = build(CFG)
    # ground truth is untouched: same documents, same answers
    assert [(d.doc_id, d.fields) for d in fd.sim.documents] == \
        [(d.doc_id, d.fields) for d in clean.sim.documents]
    assert [(q.question_id, q.template, q.answer) for q in fd.questions] == \
        [(q.question_id, q.template, q.answer) for q in clean.questions]
    # attachments keep the canonical format
    world = fd.sim.world
    for d, dc in zip(fd.sim.documents, clean.sim.documents):
        assert render_attachment(d, world) == \
            render_attachment(dc, clean.sim.world)
    # drift families render one of exactly three forms; several appear
    drift_prefixes = ("We can confirm a unit price of", "Monthly rent is",
                      "As per our review clause", "Please find attached invoice",
                      "We dispute")
    forms_seen = set()
    checked = 0
    for m in fd.render_result.messages:
        for s in m.statements:
            if s.occurrence != "canonical" or \
                    not s.text.startswith(drift_prefixes):
                continue
            checked += 1
            matched = [i for i, rx in enumerate(MONEY_FORMS)
                       if rx.search(s.text)]
            assert matched, s.text
            forms_seen.add(matched[0])
    assert checked > 20
    assert len(forms_seen) >= 2, "hash never varied the format"


def test_hard_preset_deterministic_and_screwed(tmp_path):
    m1 = write(build(HARD_CFG), tmp_path / "a")
    m2 = write(build(HARD_CFG), tmp_path / "b")
    assert m1["files"] == m2["files"]
    assert m1["counts"] == m2["counts"]
    for screw, value in HARD_PRESET.items():
        assert m1["config"][screw] == value
    rows = [json.loads(line) for line in
            (tmp_path / "a" / "ground_truth" / "evidence.jsonl")
            .read_text().splitlines()]
    occurrences = {r["occurrence"] for r in rows}
    assert occurrences == {"canonical", "quoted"}


def test_cli_preset_composes_with_explicit_flags(tmp_path, capsys):
    assert cli_main(["generate", "--seed", "5", "--months", "3",
                     "--vendors", "2", "--customers", "1",
                     "--questions", "6", "--preset", "hard",
                     "--near-dup-invoices", "0", "--no-format-drift",
                     "--out", str(tmp_path / "c")]) == 0
    manifest = json.loads((tmp_path / "c" / "manifest.json").read_text())
    cfg = manifest["config"]
    assert cfg["truncate_references"] is True   # from the preset
    assert cfg["quoted_replies"] is True        # from the preset
    assert "near_dup_invoices" not in cfg       # explicit 0 wins, omitted
    assert "format_drift" not in cfg            # explicit off wins, omitted

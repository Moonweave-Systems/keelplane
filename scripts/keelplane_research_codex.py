#!/usr/bin/env python3
"""Thin Codex driver for the research-orchestration pattern.

Runs the SAME discipline as templates/research-orchestration.workflow.mjs --
Scope -> fan-out Research -> barrier Synthesize -> adversarial Verify-against-source
-> Compose -- on the Codex substrate instead of Claude Workflow. The portable asset
is the discipline, not a swarm runner: this driver reuses the existing primitives
(parse_codex_cli builds the `codex exec` argv, run_process runs it with the prompt on
stdin) and the model-agnostic verdict-integrity core (keelplane_verdict_integrity),
rather than re-implementing codex execution. Fan-out is sequential/bounded -- live
concurrent multi-Codex is deliberately deferred (V16); parallelism is orthogonal here.

Two backends, mirroring the repo's installed-codex vs fixture split:
  - "codex":   each phase is one `codex exec --sandbox read-only --output-schema ...`
               call (prompt on stdin, schema-constrained final message read back,
               tolerant JSON extract + one retry on failure).
  - "fixture": each phase is short-circuited to a canned output from a cases file,
               so the full phase chain + integrity invariant can be tested with no
               live codex. The fixture path does NOT touch parse_codex_cli's
               security-gated fixture-command allowlist; it is a test double of the
               codex call boundary, not a second codex execution path.

The verify phase delegates to keelplane_verdict_integrity.apply_integrity (the .mjs
inlines the same logic; both are pinned to fixtures/verdict-integrity/cases.json), so
"confirmed" always means cited and a coverage gap surfaces as `uncovered`, never as a
silent confirmation.

Run the deterministic end-to-end check:  python scripts/keelplane_research_codex.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keelplane_verdict_integrity import apply_integrity  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "fixtures" / "research-codex" / "cases.json"

# ---- schemas (ported from the .mjs; written to disk for `codex --output-schema`) ----

ANGLES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["angles"],
    "properties": {
        "angles": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["key", "prompt"],
                "properties": {
                    "key": {"type": "string"},
                    "prompt": {"type": "string"},
                    "why": {"type": "string"},
                },
            },
        }
    },
}

FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["angle", "claims"],
    "properties": {
        "angle": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "statement"],
                "properties": {
                    "id": {"type": "string"},
                    "statement": {"type": "string"},
                    "support": {"type": "string"},
                    "source_hint": {"type": "string"},
                },
            },
        },
        "notes": {"type": "string"},
    },
}

DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["sections", "claims"],
    "properties": {
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["title", "body"],
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "statement", "origin_angle"],
                "properties": {
                    "id": {"type": "string"},
                    "statement": {"type": "string"},
                    "source_hint": {"type": "string"},
                    "origin_angle": {"type": "string"},
                },
            },
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
}

VERDICT_BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim_id", "verdict", "reason"],
                "properties": {
                    "claim_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": [
                            "confirmed",
                            "partially-supported",
                            "refuted",
                            "unverified",
                        ],
                    },
                    "evidence": {
                        "type": "object",
                        "properties": {
                            "locator": {"type": "string"},
                            "excerpt_or_value": {"type": "string"},
                        },
                    },
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

# ---- prompts (ported verbatim from the .mjs so both substrates ask the same thing) --


def _source_list(sources: list[str]) -> str:
    return "\n".join(f"- {s}" for s in sources) if sources else "(none supplied)"


def scope_prompt(question: str, sources: list[str]) -> str:
    src = _source_list(sources)
    ground = (
        f"Ground-truth sources that exist to check claims against:\n{src}"
        if sources
        else "No ground-truth sources were supplied."
    )
    return (
        "You are scoping a research/design question into independent investigation angles.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"{ground}\n\n"
        "Decompose the question into 3-6 distinct, non-overlapping angles. Each angle is a\n"
        "separate surface or perspective a worker can investigate without coordinating with\n"
        "the others. Avoid angles that just restate the question. Return the angles only."
    )


def research_prompt(question: str, sources: list[str], angle: dict[str, Any]) -> str:
    src = _source_list(sources)
    why = f"Why it matters: {angle['why']}" if angle.get("why") else ""
    ground = (
        f"Ground-truth sources available (read them when relevant):\n{src}"
        if sources
        else ""
    )
    return (
        "You are one research worker in a fan-out. Investigate ONLY your angle.\n\n"
        f"OVERALL QUESTION:\n{question}\n\n"
        f"YOUR ANGLE ({angle['key']}):\n{angle['prompt']}\n{why}\n\n"
        f"{ground}\n\n"
        "Return discrete, CHECKABLE claims -- each a single factual statement another agent\n"
        "could later confirm or refute against a source. Do not pad with generalities.\n"
        "For every claim give a source_hint pointing at where it could be verified.\n"
        'Do NOT label anything "verified" or "confirmed" -- that is a later phase\'s job.'
    )


def synth_prompt(question: str, findings: list[Any], doc_kind: str) -> str:
    return (
        "You are the synthesis barrier. You have ALL fan-out findings below.\n\n"
        f"OVERALL QUESTION:\n{question}\n\n"
        f"FINDINGS (JSON):\n{json.dumps(findings, indent=2)}\n\n"
        f"Produce a coherent draft {doc_kind}: ordered sections that answer the question,\n"
        "referencing claims by id. Then produce a flat `claims` list of every checkable claim\n"
        "the draft relies on. Rules for the claims list:\n"
        "- Each claim id MUST be unique across the whole draft.\n"
        "- Set origin_angle to the angle the claim came from.\n"
        "- Merge duplicate claims from different angles into ONE id (keep the clearest\n"
        "  statement + a source_hint).\n"
        "- Do NOT invent claims that no worker reported.\n"
        "Carry forward unresolved tensions as open_questions."
    )


def verify_batch_prompt(sources: list[str], claims_chunk: list[dict[str, Any]]) -> str:
    src = _source_list(sources)
    trimmed = [
        {
            "id": c.get("id"),
            "statement": c.get("statement"),
            "source_hint": c.get("source_hint"),
        }
        for c in claims_chunk
    ]
    return (
        "You are an INDEPENDENT adversarial verifier. Your job is to REFUTE these claims, not\n"
        "rubber-stamp them. You did not produce them and owe them no benefit of the doubt.\n\n"
        "Read the ground-truth sources ONCE, then judge EVERY claim below against them.\n\n"
        f"GROUND-TRUTH SOURCES you may read:\n{src}\n\n"
        f"CLAIMS (JSON):\n{json.dumps(trimmed, indent=2)}\n\n"
        "Rules:\n"
        "- Verify against GROUND TRUTH, not against the producer's reasoning. Open the actual\n"
        "  source/data/artifact yourself, read the relevant part, and cite it in evidence\n"
        "  (locator = file:line / key / url you ACTUALLY read; excerpt_or_value = the exact\n"
        "  text or number found there). The source_hint is the producer's guess -- do not\n"
        "  trust it; confirm by reading.\n"
        '- Any "verified"/"confirmed" wording attached to a claim is itself a claim to refute,\n'
        "  not a fact.\n"
        "- Verdicts:\n"
        '  - "confirmed": you read a source whose content fully supports the claim. REQUIRES\n'
        "    a real evidence locator + excerpt.\n"
        '  - "partially-supported": the source supports only a NARROWER version (the claim is\n'
        "    overstated, over-generalized, or right-in-part). REQUIRES evidence; in reason,\n"
        "    state exactly which part is unsupported and the narrower version that holds.\n"
        '  - "refuted": the ground truth contradicts the claim.\n'
        '  - "unverified": no supplied source lets you check it (default when unsure or when\n'
        "    no sources were supplied).\n"
        '- A "confirmed" or "partially-supported" verdict WITHOUT a real evidence locator is\n'
        '  invalid and will be downgraded to "unverified" -- so always cite.\n'
        "- Return EXACTLY ONE verdict per claim, each carrying the matching claim_id. Do not\n"
        "  merge, skip, invent, or relabel claim ids."
    )


def compose_prompt(
    question: str, draft: dict[str, Any], ledger: dict[str, Any], doc_kind: str
) -> str:
    return (
        f"You are composing the final {doc_kind}.\n\n"
        f"OVERALL QUESTION:\n{question}\n\n"
        f"DRAFT (sections + claims, JSON):\n{json.dumps(draft, indent=2)}\n\n"
        "VERIFICATION LEDGER (JSON: confirmed / partial / refuted / unverified / uncovered):\n"
        f"{json.dumps(ledger, indent=2)}\n\n"
        "Write the final document in Markdown:\n"
        "- Build the argument on CONFIRMED claims; cite each one's evidence locator inline.\n"
        "- For PARTIALLY-SUPPORTED claims, assert ONLY the narrower supported version stated\n"
        "  in the verdict's reason, and cite the locator. Never assert the overstated form.\n"
        "- Treat REFUTED, UNVERIFIED, and UNCOVERED claims as NOT established: do not assert\n"
        "  their content anywhere in the prose, even if it appears in the draft sections.\n"
        '- Add a short "Unverified / open" section listing (i) refuted claims (with why),\n'
        "  (ii) unverified claims, (iii) uncovered claims (ledger.uncovered -- no verdict\n"
        "  because a verifier batch failed or skipped them; they were NOT checked), and\n"
        "  (iv) open questions.\n"
        '- End with a "Verification summary" line: counts of confirmed / partial / refuted /\n'
        "  unverified / uncovered.\n"
        "Return the Markdown document only -- no preamble."
    )


# ---- backend plumbing -------------------------------------------------------


def extract_json(text: str) -> Any | None:
    """Tolerant JSON extract: codex --output-schema yields a JSON object, but guard
    against a fenced block or surrounding prose as a backstop."""
    text = (text or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*([\[{].*[\]}])\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def has_required(obj: Any, required_keys: list[str] | None) -> bool:
    if not isinstance(obj, dict):
        return False
    return all(key in obj for key in (required_keys or []))


# OpenAI strict structured-outputs (what `codex exec --output-schema` enforces) rejects
# a schema unless every object sets additionalProperties:false AND lists every property
# in `required`, and it does not accept validation keywords like minItems. The .mjs-parity
# schemas above are intentionally permissive (Workflow's schema layer is laxer); strictify
# them only when handing the file to codex, so the source schemas stay readable.
_STRICT_DROP_KEYS = {
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "format",
    "default",
    "uniqueItems",
}


def strictify_schema(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {
            key: strictify_schema(value)
            for key, value in node.items()
            if key not in _STRICT_DROP_KEYS
        }
        if out.get("type") == "object" and isinstance(out.get("properties"), dict):
            out["additionalProperties"] = False
            out["required"] = list(out["properties"].keys())
        return out
    if isinstance(node, list):
        return [strictify_schema(item) for item in node]
    return node


def _codex_phase(
    prompt: str,
    schema: dict[str, Any] | None,
    *,
    label: str,
    work_dir: Path,
    wt_path: Path,
    expect_json: bool,
    required_keys: list[str] | None,
) -> tuple[str, Any, str]:
    # Lazy import: the fixture path (and --self-test) never needs the heavyweight module.
    from execute_packet import parse_codex_cli, run_process

    phase_dir = work_dir / label.replace(":", "_")
    phase_dir.mkdir(parents=True, exist_ok=True)
    config: dict[str, Any] = {"mode": "installed-codex", "sandbox": "read-only"}
    if schema is not None:
        schema_path = phase_dir / "schema.json"
        schema_path.write_text(json.dumps(strictify_schema(schema)))
        config["output_schema"] = str(schema_path)
    argv, expected_exit, _mode, timeout = parse_codex_cli(
        config, attempt_dir=phase_dir, wt_path=wt_path
    )
    process = run_process(argv, wt_path, input_text=prompt, timeout_seconds=timeout)
    transcript = phase_dir / "transcript.md"
    raw = transcript.read_text() if transcript.exists() else (process.stdout or "")
    ok = process.returncode == expected_exit
    if not expect_json:
        return ("executed" if ok and raw.strip() else "failed", raw, raw)
    parsed = extract_json(raw) if ok else None
    if parsed is not None and has_required(parsed, required_keys):
        return "executed", parsed, raw
    return "failed", None, raw


def _fixture_phase(
    fixture: dict[str, Any],
    label: str,
    *,
    expect_json: bool,
    required_keys: list[str] | None,
) -> tuple[str, Any, str]:
    entry = fixture.get(label)
    if entry is None:
        return "failed", None, ""
    if not expect_json:
        text = entry if isinstance(entry, str) else json.dumps(entry)
        return ("executed" if text.strip() else "failed", text, text)
    if not has_required(entry, required_keys):
        return "failed", None, json.dumps(entry)
    return "executed", entry, json.dumps(entry)


def run_phase(
    backend: str,
    fixture: dict[str, Any] | None,
    *,
    label: str,
    prompt: str,
    schema: dict[str, Any] | None,
    required_keys: list[str] | None,
    expect_json: bool,
    work_dir: Path | None,
    wt_path: Path | None,
) -> tuple[str, Any, str]:
    if backend == "fixture":
        return _fixture_phase(
            fixture or {}, label, expect_json=expect_json, required_keys=required_keys
        )
    assert work_dir is not None and wt_path is not None
    status, parsed, raw = _codex_phase(
        prompt,
        schema,
        label=label,
        work_dir=work_dir,
        wt_path=wt_path,
        expect_json=expect_json,
        required_keys=required_keys,
    )
    if status == "failed":  # one retry: a transient blip should not drop a phase
        status, parsed, raw = _codex_phase(
            prompt,
            schema,
            label=f"{label}-retry",
            work_dir=work_dir,
            wt_path=wt_path,
            expect_json=expect_json,
            required_keys=required_keys,
        )
    return status, parsed, raw


def chunk(items: list[Any], size: int) -> list[list[Any]]:
    if size < 1:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


# ---- orchestration ----------------------------------------------------------


def orchestrate(
    question: str,
    sources: list[str],
    *,
    angles: list[dict[str, Any]] | None = None,
    backend: str = "codex",
    fixture: dict[str, Any] | None = None,
    verify_batch_size: int = 8,
    work_dir: Path | None = None,
    wt_path: Path | None = None,
    doc_kind: str = "design document",
) -> dict[str, Any]:
    sources = [s for s in sources if isinstance(s, str) and s.strip()]
    phase_status: dict[str, str] = {}

    def call(label, prompt, schema, required_keys, expect_json):
        return run_phase(
            backend,
            fixture,
            label=label,
            prompt=prompt,
            schema=schema,
            required_keys=required_keys,
            expect_json=expect_json,
            work_dir=work_dir,
            wt_path=wt_path,
        )

    # Scope (skipped if angles supplied)
    angles = [
        a
        for a in (angles or [])
        if isinstance(a, dict) and a.get("key") and a.get("prompt")
    ]
    if not angles:
        status, parsed, _ = call(
            "scope",
            scope_prompt(question, sources),
            ANGLES_SCHEMA,
            ["angles"],
            True,
        )
        phase_status["scope"] = status
        scoped = (parsed or {}).get("angles", []) if parsed else []
        angles = [
            a
            for a in scoped
            if isinstance(a, dict) and a.get("key") and a.get("prompt")
        ]
    if not angles:
        raise SystemExit("research-codex: no angles to research (scoping failed)")

    # Research (sequential fan-out; concurrency deferred per V16)
    findings: list[Any] = []
    for angle in angles:
        status, parsed, _ = call(
            f"research:{angle['key']}",
            research_prompt(question, sources, angle),
            FINDINGS_SCHEMA,
            ["angle", "claims"],
            True,
        )
        phase_status[f"research:{angle['key']}"] = status
        if parsed:
            findings.append(parsed)
    if not findings:
        raise SystemExit("research-codex: every research worker failed")

    # Synthesize (barrier: needs the complete finding set to de-dup across angles)
    status, draft, _ = call(
        "synthesize",
        synth_prompt(question, findings, doc_kind),
        DRAFT_SCHEMA,
        ["sections", "claims"],
        True,
    )
    phase_status["synthesize"] = status
    if not draft:
        raise SystemExit("research-codex: synthesis failed -- nothing to verify")
    claims = draft.get("claims") or []

    # Verify (batched, sequential): each batch reads the sources once
    raw_verdicts: list[dict[str, Any]] = []
    for index, batch in enumerate(chunk(claims, verify_batch_size)):
        label = f"verify:batch-{index + 1}"
        status, parsed, _ = call(
            label,
            verify_batch_prompt(sources, batch),
            VERDICT_BATCH_SCHEMA,
            ["verdicts"],
            True,
        )
        phase_status[label] = status
        if parsed and isinstance(parsed.get("verdicts"), list):
            raw_verdicts.extend(parsed["verdicts"])

    # Integrity pass (shared model-agnostic core): confirmed => cited, gaps => uncovered
    ledger = apply_integrity(claims, raw_verdicts)
    compose_ledger = {
        "confirmed": ledger["confirmed"],
        "partial": ledger["partial"],
        "refuted": ledger["refuted"],
        "unverified": ledger["unverified"],
        "uncovered": ledger["uncovered"],
    }

    # Compose
    status, doc, _ = call(
        "compose",
        compose_prompt(question, draft, compose_ledger, doc_kind),
        None,
        None,
        False,
    )
    phase_status["compose"] = status

    return {
        "doc": doc if status == "executed" else None,
        "confirmed": ledger["confirmed"],
        "partial": ledger["partial"],
        "refuted": ledger["refuted"],
        "unverified": ledger["unverified"],
        "uncovered": ledger["uncovered"],
        "dropped": ledger["dropped"],
        "downgraded": ledger["downgraded"],
        "claimCount": len(claims),
        "angles": angles,
        "phase_status": phase_status,
    }


# ---- self-test (fixture-backed end-to-end) ----------------------------------


def _strict_violations(node: Any, path: str = "$") -> list[str]:
    """Every object node a codex --output-schema sees must set additionalProperties:false
    and list all properties in `required`, with no unsupported validation keywords left.
    A live codex run 400s on any violation (slice 4 finding), so guard it without codex."""
    issues: list[str] = []
    if isinstance(node, dict):
        leftover = set(node) & _STRICT_DROP_KEYS
        if leftover:
            issues.append(f"{path}: unsupported keyword(s) {sorted(leftover)}")
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            if node.get("additionalProperties") is not False:
                issues.append(f"{path}: additionalProperties must be false")
            if sorted(node.get("required", [])) != sorted(node["properties"]):
                issues.append(f"{path}: required must list every property")
        for key, value in node.items():
            issues += _strict_violations(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            issues += _strict_violations(item, f"{path}[{index}]")
    return issues


def self_test() -> None:
    failures: list[str] = []
    for name, schema in (
        ("angles", ANGLES_SCHEMA),
        ("findings", FINDINGS_SCHEMA),
        ("draft", DRAFT_SCHEMA),
        ("verdict_batch", VERDICT_BATCH_SCHEMA),
    ):
        for issue in _strict_violations(strictify_schema(schema)):
            failures.append(f"strictify[{name}]: {issue}")

    cases = json.loads(CASES_PATH.read_text())["cases"]
    for case in cases:
        result = orchestrate(
            case["question"],
            case["sources"],
            backend="fixture",
            fixture=case["fixtures"],
            verify_batch_size=case.get("verify_batch_size", 8),
            doc_kind=case.get("doc_kind", "design document"),
        )
        expect = case["expect"]
        got = {
            "angleCount": len(result["angles"]),
            "claimCount": result["claimCount"],
            "confirmed": len(result["confirmed"]),
            "partial": len(result["partial"]),
            "refuted": len(result["refuted"]),
            "unverified": len(result["unverified"]),
            "uncovered": sorted(c.get("id") for c in result["uncovered"]),
            "dropped": result["dropped"],
            "downgraded": result["downgraded"],
        }
        for key in (
            "angleCount",
            "claimCount",
            "confirmed",
            "partial",
            "refuted",
            "unverified",
            "dropped",
            "downgraded",
        ):
            if got[key] != expect[key]:
                failures.append(
                    f"{case['name']}: {key} expected {expect[key]}, got {got[key]}"
                )
        if got["uncovered"] != sorted(expect["uncovered"]):
            failures.append(
                f"{case['name']}: uncovered expected {sorted(expect['uncovered'])}, got {got['uncovered']}"
            )
        bucketed = (
            got["confirmed"] + got["partial"] + got["refuted"] + got["unverified"]
        )
        if bucketed + len(got["uncovered"]) != got["claimCount"]:
            failures.append(
                f"{case['name']}: invariant broken (bucketed {bucketed} + uncovered {len(got['uncovered'])} != claims {got['claimCount']})"
            )
        if not (isinstance(result["doc"], str) and result["doc"].strip()):
            failures.append(f"{case['name']}: compose produced no document")
        failed_phases = [
            k for k, v in result["phase_status"].items() if v != "executed"
        ]
        if failed_phases:
            failures.append(f"{case['name']}: phases not executed: {failed_phases}")

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        raise SystemExit(f"research-codex self-test: {len(failures)} failure(s)")
    print(
        f"research-codex self-test: pass (4 schemas strict, {len(cases)} e2e case(s))"
    )


# ---- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Thin Codex driver for the research-orchestration pattern."
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--question")
    parser.add_argument(
        "--source", action="append", default=[], help="ground-truth source (repeatable)"
    )
    parser.add_argument(
        "--angles", help="JSON array of {key, prompt, why} (skips scope)"
    )
    parser.add_argument("--backend", choices=["codex", "fixture"], default="codex")
    parser.add_argument(
        "--fixture", help="path to a fixtures cases file (fixture backend)"
    )
    parser.add_argument("--case", help="case name within the fixtures file")
    parser.add_argument("--work-dir", help="scratch dir for codex transcripts/schemas")
    parser.add_argument("--cd", help="codex --cd worktree path (default: repo root)")
    parser.add_argument("--verify-batch-size", type=int, default=8)
    parser.add_argument("--doc-kind", default="design document")
    parser.add_argument("--out", help="write the composed doc here")
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        return 0

    if not args.question:
        parser.error("provide --self-test, or --question")

    angles = json.loads(args.angles) if args.angles else None
    fixture = None
    if args.backend == "fixture":
        if not args.fixture or not args.case:
            parser.error("fixture backend requires --fixture and --case")
        cases = json.loads(Path(args.fixture).read_text())["cases"]
        case = next((c for c in cases if c["name"] == args.case), None)
        if case is None:
            parser.error(f"case not found: {args.case}")
        fixture = case["fixtures"]

    work_dir = (
        Path(args.work_dir).resolve() if args.work_dir else ROOT / ".research-codex"
    )
    wt_path = Path(args.cd).resolve() if args.cd else ROOT

    result = orchestrate(
        args.question,
        args.source,
        angles=angles,
        backend=args.backend,
        fixture=fixture,
        verify_batch_size=args.verify_batch_size,
        work_dir=work_dir,
        wt_path=wt_path,
        doc_kind=args.doc_kind,
    )

    if args.out and result["doc"]:
        Path(args.out).write_text(result["doc"])
    summary = {
        "confirmed": len(result["confirmed"]),
        "partial": len(result["partial"]),
        "refuted": len(result["refuted"]),
        "unverified": len(result["unverified"]),
        "uncovered": sorted(c.get("id") for c in result["uncovered"]),
        "dropped": result["dropped"],
        "downgraded": result["downgraded"],
        "claimCount": result["claimCount"],
        "phase_status": result["phase_status"],
        "doc_written": bool(args.out and result["doc"]),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

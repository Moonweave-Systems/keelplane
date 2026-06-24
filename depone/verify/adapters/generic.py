from __future__ import annotations

import hashlib
import json
from pathlib import Path

from depone.verify.adapters.base import EvidenceContext, EvidenceFile


def read_evidence(evidence_dir: str) -> EvidenceContext:
    """Read all files in a directory as generic execution evidence.

    Every file under evidence_dir is discovered, hashed, and returned.
    Subdirectories are walked recursively. Binary files are stored as
    hex strings; text files are stored as-is.
    """
    root = Path(evidence_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"evidence_dir is not a directory: {evidence_dir}")

    files: list[EvidenceFile] = []
    run_id: str | None = None
    raw: dict = {}

    for entry in sorted(root.rglob("*")):
        if entry.is_dir():
            continue
        rel = entry.relative_to(root).as_posix()
        content_bytes = entry.read_bytes()
        sha = hashlib.sha256(content_bytes).hexdigest()

        # Try to decode as text; fall back to base64
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            content = content_bytes.hex()

        files.append(EvidenceFile(path=rel, content=content, sha256=sha))

        # Check for run metadata in known files
        if rel == "run-metadata.json":
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    raw["metadata"] = parsed
                    run_id = parsed.get("run_id")
            except json.JSONDecodeError:
                pass

    return EvidenceContext(run_id=run_id, files=files, raw=raw)

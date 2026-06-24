from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class EvidenceFile:
    """A single evidence file found in the execution output."""
    path: str
    content: str
    sha256: str


@dataclass
class EvidenceContext:
    """Aggregated evidence from an execution run."""
    run_id: str | None
    files: list[EvidenceFile]
    raw: dict  # adapter-specific metadata (logs, timestamps, etc.)


class EvidenceAdapter(Protocol):
    """Protocol for reading execution evidence from a framework output dir.

    Each adapter knows how to:
    1. Discover evidence files in a directory
    2. Extract run metadata (run_id, timestamps, agent invocations)
    3. Read plan-specific artifacts referenced in handoffs
    """

    name: str

    def read_evidence(self, evidence_dir: str) -> EvidenceContext:
        """Read & hash all evidence in a directory, returning structured context."""
        ...

"""
Data model for Phase 1.1 (Repository Acquisition).

PLAN.md Phase 1.1 acceptance criteria this module encodes directly:
  - "Analysis cannot start without an identified repository version"
    -> RepositoryInfo.require_commit() raises unless status is SUCCESS and a
       commit_sha was captured.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path


class AcquisitionStatus(enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RepositoryInfo:
    source: str
    local_path: Path | None
    status: AcquisitionStatus
    commit_sha: str | None

    file_count: int
    language_counts: dict[str, int]
    repository_size_bytes: int

    clone_start: float
    clone_end: float
    clone_duration_seconds: float

    error_reason: str | None = None

    @property
    def language_count(self) -> int:
        return len(self.language_counts)

    def require_commit(self) -> str:
        """
        Enforces the Phase 1.1 acceptance criterion: "Analysis cannot start
        without an identified repository version." Callers in later phases
        (M2+) must go through this rather than reading commit_sha directly.
        """
        if self.status is not AcquisitionStatus.SUCCESS or not self.commit_sha:
            raise ValueError(
                f"Repository version not identified for source={self.source!r} "
                f"(status={self.status.value}, error={self.error_reason!r}); "
                "analysis cannot proceed."
            )
        return self.commit_sha

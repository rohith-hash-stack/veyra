"""
PLAN.md Phase 1.4 -- Git Version Tracking (file-level).

Scope note: this is the file-level tracking Phase 1.4 asks for directly
(Added/Modified/Deleted/Renamed/Unchanged). The D4 extension -- a
symbol-level diff pass classifying ADDED/REMOVED/MODIFIED_SIGNATURE/
MODIFIED_BODY/UNCHANGED per node -- is explicitly deferred until Milestone
2's structural graph exists to diff (there are no Nodes to compare yet). See
PROGRESS.md.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ChangeType(enum.Enum):
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    RENAMED = "RENAMED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True)
class FileChange:
    path: str
    change_type: ChangeType
    previous_path: str | None = None  # set only for RENAMED

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("FileChange.path is required.")
        if not isinstance(self.change_type, ChangeType):
            raise TypeError("FileChange.change_type must be a ChangeType member.")
        if self.change_type is ChangeType.RENAMED and not self.previous_path:
            raise ValueError("RENAMED changes must set previous_path.")

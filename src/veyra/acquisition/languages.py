"""
Deterministic, extension-based language inventory for repository acquisition
metadata (PLAN.md Phase 1.1: "Identify languages").

This is intentionally NOT a parser and makes no attempt at completeness beyond
inventory/audit purposes -- Milestone 2 (Phase 2.1) owns real per-language
structural extraction. A file with an unrecognized extension is still counted
in the overall file_count by the caller; it is simply excluded from the
per-language breakdown here.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".java": "Java",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".m": "Objective-C",
    ".sh": "Shell",
}


def identify_languages(files: list[Path]) -> dict[str, int]:
    """Return {language: file_count}, sorted by language name for determinism."""
    counts: Counter[str] = Counter()
    for path in files:
        language = LANGUAGE_EXTENSIONS.get(path.suffix.lower())
        if language is not None:
            counts[language] += 1
    return dict(sorted(counts.items()))

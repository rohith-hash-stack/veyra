"""
PLAN.md Milestone 3 -- Dependency Inspection, the first stage of the
"dependency installation is a security operation" pipeline the user's M3
spec calls for (Dependency Inspection -> Installation Policy -> Environment
Construction; see PLAN.md Phase 3.2's note). This module only ever reads and
parses manifest files -- it never runs `pip`, never resolves version
constraints against an index, and never imports or executes repository
code. A manifest this can't parse yields an empty package set for that file,
never a guess.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class DependencyManifest:
    declared_packages: tuple[str, ...]
    manifest_files: tuple[str, ...]


def _package_name(spec: str) -> str | None:
    match = _NAME_RE.match(spec.strip())
    return match.group(0).lower() if match else None


def _parse_requirements_txt(path: Path) -> set[str]:
    packages: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue  # blank, comment, or an option/editable/reference line (-e, -r, --hash, ...)
        name = _package_name(line)
        if name:
            packages.add(name)
    return packages


def _parse_pyproject_toml(path: Path) -> set[str]:
    packages: set[str] = set()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return packages
    project = data.get("project", {})
    for spec in project.get("dependencies", []):
        name = _package_name(spec)
        if name:
            packages.add(name)
    for group in project.get("optional-dependencies", {}).values():
        for spec in group:
            name = _package_name(spec)
            if name:
                packages.add(name)
    return packages


def inspect_dependencies(repository_root: Path) -> DependencyManifest:
    packages: set[str] = set()
    manifest_files: list[str] = []

    requirements_path = repository_root / "requirements.txt"
    if requirements_path.is_file():
        packages |= _parse_requirements_txt(requirements_path)
        manifest_files.append("requirements.txt")

    pyproject_path = repository_root / "pyproject.toml"
    if pyproject_path.is_file():
        packages |= _parse_pyproject_toml(pyproject_path)
        manifest_files.append("pyproject.toml")

    return DependencyManifest(
        declared_packages=tuple(sorted(packages)),
        manifest_files=tuple(manifest_files),
    )

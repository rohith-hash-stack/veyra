from __future__ import annotations

from pathlib import Path
from typing import Callable

from veyra.harness import inspect_dependencies


def test_no_manifest_yields_empty_manifest(repo_root: Path) -> None:
    manifest = inspect_dependencies(repo_root)
    assert manifest.declared_packages == ()
    assert manifest.manifest_files == ()


def test_parses_requirements_txt(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file(
        "requirements.txt",
        "# a comment\n"
        "\n"
        "requests==2.31.0\n"
        "flask>=2.0,<3.0\n"
        "-e git+https://example.com/pkg.git#egg=editable-pkg\n"
        "-r other.txt\n",
    )
    manifest = inspect_dependencies(repo_root)
    assert manifest.declared_packages == ("flask", "requests")
    assert manifest.manifest_files == ("requirements.txt",)


def test_parses_pyproject_toml_project_dependencies(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file(
        "pyproject.toml",
        "[project]\n"
        'name = "x"\n'
        'dependencies = ["httpx>=0.27", "pydantic"]\n'
        "\n"
        "[project.optional-dependencies]\n"
        'dev = ["pytest>=8"]\n',
    )
    manifest = inspect_dependencies(repo_root)
    assert manifest.declared_packages == ("httpx", "pydantic", "pytest")
    assert manifest.manifest_files == ("pyproject.toml",)


def test_malformed_pyproject_toml_yields_no_packages_not_a_crash(
    write_file: Callable[[str, str], Path], repo_root: Path
) -> None:
    write_file("pyproject.toml", "this is not valid toml [[[")
    manifest = inspect_dependencies(repo_root)
    assert manifest.declared_packages == ()
    assert manifest.manifest_files == ("pyproject.toml",)


def test_combines_both_manifests(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file("requirements.txt", "requests\n")
    write_file("pyproject.toml", '[project]\ndependencies = ["httpx"]\n')
    manifest = inspect_dependencies(repo_root)
    assert manifest.declared_packages == ("httpx", "requests")
    assert set(manifest.manifest_files) == {"requirements.txt", "pyproject.toml"}


def test_stdlib_only_project_with_pyproject_but_no_dependencies_is_empty(
    write_file: Callable[[str, str], Path], repo_root: Path
) -> None:
    write_file("pyproject.toml", '[project]\nname = "x"\ndependencies = []\n')
    manifest = inspect_dependencies(repo_root)
    assert manifest.declared_packages == ()
    assert manifest.manifest_files == ("pyproject.toml",)

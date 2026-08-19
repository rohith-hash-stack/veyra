from __future__ import annotations

from pathlib import Path
from typing import Callable

from veyra.harness import discover_tests


def test_discovers_module_level_pytest_style_function(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file("test_math.py", "def test_add():\n    assert 1 + 1 == 2\n")
    found = discover_tests(repo_root)
    assert len(found) == 1
    assert found[0].entity_id == "test_math.test_add"
    assert found[0].class_name is None
    assert found[0].function_name == "test_add"
    assert found[0].module_path == "test_math.py"


def test_discovers_unittest_style_class_methods(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file(
        "test_widget.py",
        "import unittest\n\n"
        "class TestWidget(unittest.TestCase):\n"
        "    def test_one(self):\n        self.assertTrue(True)\n\n"
        "    def test_two(self):\n        self.assertTrue(True)\n\n"
        "    def helper(self):\n        pass\n",
    )
    found = discover_tests(repo_root)
    entity_ids = {t.entity_id for t in found}
    assert entity_ids == {"test_widget.TestWidget.test_one", "test_widget.TestWidget.test_two"}
    assert all(t.class_name == "TestWidget" for t in found)


def test_ignores_non_test_files(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file("utils.py", "def test_looking_helper():\n    pass\n")
    assert discover_tests(repo_root) == []


def test_ignores_non_test_prefixed_classes(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file(
        "test_thing.py",
        "class Helper:\n    def test_x(self):\n        pass\n",
    )
    assert discover_tests(repo_root) == []


def test_ignores_non_test_functions_and_methods(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file(
        "test_thing.py",
        "def helper():\n    pass\n\n"
        "class TestThing:\n"
        "    def setUp(self):\n        pass\n"
        "    def test_real(self):\n        pass\n",
    )
    found = discover_tests(repo_root)
    assert {t.function_name for t in found} == {"test_real"}


def test_unparsable_test_file_yields_no_tests_not_a_crash(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file("test_broken.py", "def test_bad(:\n    pass\n")
    assert discover_tests(repo_root) == []


def test_matches_test_suffix_filename_convention(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file("widget_test.py", "def test_it():\n    assert True\n")
    found = discover_tests(repo_root)
    assert len(found) == 1
    assert found[0].entity_id == "widget_test.test_it"


def test_discovery_is_deterministic(write_file: Callable[[str, str], Path], repo_root: Path) -> None:
    write_file("test_a.py", "def test_one():\n    assert True\n\ndef test_two():\n    assert True\n")
    write_file("sub/test_b.py", "def test_three():\n    assert True\n")
    first = discover_tests(repo_root)
    second = discover_tests(repo_root)
    assert first == second
    assert {t.entity_id for t in first} == {"test_a.test_one", "test_a.test_two", "sub.test_b.test_three"}

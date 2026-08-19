from __future__ import annotations

from veyra.scenarios import extract_signature
from veyra.vbg import Node

COMMIT = "commit1"


def make_node(entity_id: str, source: str, node_type: str = "Function") -> Node:
    """Builds a Node the way Phase 2.1's extractor would -- lexical_representation
    holding the exact function source -- without needing a real repo on disk.
    Defined locally (not imported from a shared conftest) because pytest's
    default import mode has no package structure across tests/* directories
    (no __init__.py anywhere -- see PROGRESS.md's Phase 3.1 note on the
    test_audit.py collision), so a bare `from conftest import X` can silently
    resolve to a different directory's conftest.py within the same run."""
    return Node(
        entity_id=entity_id,
        type=node_type,
        name=entity_id.rsplit(".", 1)[-1],
        repository_version=COMMIT,
        language="Python",
        lexical_representation=source,
    )


def test_zero_arg_function_has_no_parameters() -> None:
    node = make_node("mod.foo", "def foo():\n    return 1\n")
    sig = extract_signature(node)
    assert sig.parameters == ()
    assert sig.is_bound_method is False


def test_primitive_annotated_parameter_is_synthesizable() -> None:
    node = make_node("mod.foo", "def foo(x: int, y: str) -> None:\n    pass\n")
    sig = extract_signature(node)
    assert [p.name for p in sig.parameters] == ["x", "y"]
    assert all(p.synthesizable for p in sig.parameters)


def test_unannotated_parameter_without_default_is_not_synthesizable() -> None:
    node = make_node("mod.foo", "def foo(x):\n    pass\n")
    sig = extract_signature(node)
    assert sig.parameters[0].synthesizable is False


def test_parameter_with_default_is_synthesizable_even_without_annotation() -> None:
    node = make_node("mod.foo", "def foo(x=5):\n    pass\n")
    sig = extract_signature(node)
    assert sig.parameters[0].has_default is True
    assert sig.parameters[0].synthesizable is True


def test_complex_annotation_is_not_synthesizable() -> None:
    node = make_node("mod.foo", "def foo(x: 'SomeClass'):\n    pass\n")
    sig = extract_signature(node)
    assert sig.parameters[0].annotation == "SomeClass"
    assert sig.parameters[0].synthesizable is False


def test_bound_method_self_is_excluded_from_parameters() -> None:
    node = make_node("mod.Cls.foo", "def foo(self, x: int):\n    pass\n", node_type="Method")
    sig = extract_signature(node)
    assert sig.is_bound_method is True
    assert [p.name for p in sig.parameters] == ["x"]


def test_classmethod_cls_is_excluded_from_parameters() -> None:
    node = make_node("mod.Cls.foo", "def foo(cls):\n    pass\n", node_type="Method")
    sig = extract_signature(node)
    assert sig.parameters == ()


def test_kwonly_parameter_without_default_is_not_synthesizable() -> None:
    node = make_node("mod.foo", "def foo(*, x):\n    pass\n")
    sig = extract_signature(node)
    assert sig.parameters[0].name == "x"
    assert sig.parameters[0].synthesizable is False


def test_kwonly_parameter_with_default_is_synthesizable() -> None:
    node = make_node("mod.foo", "def foo(*, x=1):\n    pass\n")
    sig = extract_signature(node)
    assert sig.parameters[0].synthesizable is True


def test_var_positional_and_var_keyword_are_flagged_not_required() -> None:
    node = make_node("mod.foo", "def foo(*args, **kwargs):\n    pass\n")
    sig = extract_signature(node)
    assert sig.parameters == ()
    assert sig.has_var_positional is True
    assert sig.has_var_keyword is True


def test_no_lexical_representation_returns_none() -> None:
    node = make_node("mod.foo", "")
    assert extract_signature(node) is None


def test_unparsable_source_returns_none() -> None:
    node = make_node("mod.foo", "def foo(:\n    pass\n")
    assert extract_signature(node) is None

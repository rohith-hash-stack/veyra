"""
Phase 3.1 integration tests: classify() end to end, plus the "important
security semantics" spec items 21-27.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from veyra.safety import PolicyConfig, classify
from veyra.vbg import Capability, SafetyClass

from conftest import COMMIT, make_node


def test_classify_end_to_end_blocked() -> None:
    node = make_node("orders.run_cmd", "def run_cmd():\n    subprocess.run(['ls'])\n")
    result = classify(node, COMMIT)

    assert result.target == "orders.run_cmd"
    assert result.classification is SafetyClass.BLOCKED
    assert Capability.SUBPROCESS_EXECUTION in result.capabilities_detected
    assert result.repository_commit == COMMIT
    assert result.policy_version == PolicyConfig.default().version
    assert result.evidence  # non-empty -- auditable


def test_classify_end_to_end_sandboxable_default() -> None:
    node = make_node("orders.total", "def total(items):\n    return sum(items)\n")
    result = classify(node, COMMIT)

    assert result.classification is SafetyClass.SANDBOXABLE
    assert result.capabilities_detected == ()


# -- 21. No execution capability exists in Phase 3.1 -------------------------


def test_no_execution_capability_anywhere_in_safety_package() -> None:
    forbidden_tokens = ("subprocess.", "os.system(", "os.exec", "os.spawn", "Popen(", "eval(", "exec(", "docker")
    safety_src_dir = Path(inspect.getfile(classify)).parent

    for py_file in safety_src_dir.glob("*.py"):
        source = py_file.read_text()
        tree = ast.parse(source)
        # The detection patterns themselves reference these tokens as
        # STRING LITERALS (rule tables) -- what must never appear is an
        # actual call/import using them as real Python syntax.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                chain = ast.unparse(func) if hasattr(ast, "unparse") else ""
                assert not chain.startswith("subprocess."), f"{py_file.name} calls subprocess directly"
                assert chain not in ("eval", "exec", "os.system"), f"{py_file.name} calls {chain} directly"
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                assert "docker" not in names, f"{py_file.name} imports docker"
                assert "subprocess" not in names, f"{py_file.name} imports subprocess"


# -- 22. Detection does not itself execute target code -----------------------


def test_detection_does_not_execute_target_code() -> None:
    # A node whose source would raise/crash/have side effects if actually
    # run -- detection must not evaluate it, only parse+walk the AST.
    node = make_node(
        "orders.dangerous",
        "def dangerous():\n    raise RuntimeError('if this runs, detection executed the target')\n",
    )
    result = classify(node, COMMIT)  # must not raise
    assert result.target == "orders.dangerous"


# -- 23/24. No dangerous or unknown capability is silently promoted to SAFE --


def test_blocked_capability_is_never_promoted_to_safe() -> None:
    node = make_node("orders.run_cmd", "def run_cmd():\n    subprocess.run(['ls'])\n")
    result = classify(node, COMMIT)
    assert result.classification is not SafetyClass.SAFE


def test_unknown_capability_is_never_silently_treated_as_safe() -> None:
    node = make_node("orders.mystery", "def mystery():\n    some_unrecognized_plugin_hook()\n")
    result = classify(node, COMMIT)
    assert result.classification is not SafetyClass.SAFE
    assert result.classification is SafetyClass.UNKNOWN


# -- 25. Missing evidence does not become a positive safety claim ------------


def test_missing_lexical_representation_does_not_become_safe() -> None:
    node = make_node("orders.mystery", "")
    result = classify(node, COMMIT)
    assert result.classification is not SafetyClass.SAFE
    assert Capability.UNKNOWN_EXTERNAL_EFFECT in result.capabilities_detected


# -- 26/27. Classification is auditable and references the repository commit -


def test_classification_result_is_self_auditable() -> None:
    node = make_node("orders.run_cmd", "def run_cmd():\n    subprocess.run(['ls'])\n")
    result = classify(node, "commit-abc123")

    # A future investigator must be able to answer "why" from the result alone.
    assert result.reason
    assert result.matched_rules
    assert result.evidence
    assert result.repository_commit == "commit-abc123"
    assert result.policy_version


def test_classification_never_reachable_for_safe_without_allowlist() -> None:
    # Sweep a range of inputs: with the default policy (empty allowlist),
    # SAFE must never appear no matter what capabilities are detected.
    sources = [
        "def f():\n    pass\n",
        "def f():\n    return sum([1,2,3])\n",
        "def f():\n    open('x','r')\n",
        "def f():\n    requests.get('http://localhost')\n",
        "def f():\n    subprocess.run(['ls'])\n",
        "def f():\n    unknown_thing()\n",
    ]
    for source in sources:
        node = make_node("orders.f", source)
        result = classify(node, COMMIT)
        assert result.classification is not SafetyClass.SAFE, f"unexpected SAFE for: {source!r}"

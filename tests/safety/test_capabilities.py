"""
Phase 3.1 capability detection tests (spec items 1-10). These validate
behavior against real capability sets, not source-string matching --
"given this function body, detected capabilities = Y."
"""

from __future__ import annotations

from veyra.safety import detect_capabilities
from veyra.vbg import Capability, Node

COMMIT = "commit1"


# Defined locally, not imported from conftest -- see
# tests/execution/test_docker_boundary.py's identical comment for why.
def make_node(entity_id: str, source: str, node_type: str = "Function") -> Node:
    return Node(
        entity_id=entity_id, type=node_type, name=entity_id.rsplit(".", 1)[-1],
        repository_version=COMMIT, language="Python", lexical_representation=source,
    )


def _capabilities(node) -> set[Capability]:
    return {s.capability for s in detect_capabilities(node)}


def test_subprocess_detection() -> None:
    node = make_node("orders.run_cmd", "def run_cmd():\n    subprocess.run(['ls'])\n")
    caps = _capabilities(node)
    assert Capability.SUBPROCESS_EXECUTION in caps
    assert Capability.PROCESS_EXECUTION in caps


def test_process_execution_detection_via_os_system() -> None:
    node = make_node("orders.run_cmd", "def run_cmd():\n    os.system('rm -rf /tmp/x')\n")
    caps = _capabilities(node)
    assert Capability.PROCESS_EXECUTION in caps
    assert Capability.SUBPROCESS_EXECUTION not in caps  # os.system, not subprocess specifically


def test_network_detection() -> None:
    node = make_node("orders.notify", "def notify():\n    requests.post('https://api.stripe.com/charge')\n")
    caps = _capabilities(node)
    assert Capability.NETWORK_ACCESS in caps
    assert Capability.EXTERNAL_NETWORK_ACCESS in caps  # literal external-looking URL


def test_network_detection_local_url_is_not_flagged_external() -> None:
    node = make_node("orders.notify", "def notify():\n    requests.post('http://localhost:8080/hook')\n")
    caps = _capabilities(node)
    assert Capability.NETWORK_ACCESS in caps
    assert Capability.EXTERNAL_NETWORK_ACCESS not in caps


def test_socket_detection() -> None:
    node = make_node("orders.connect", "def connect():\n    socket.socket()\n")
    caps = _capabilities(node)
    assert Capability.SOCKET_ACCESS in caps
    assert Capability.NETWORK_ACCESS in caps


def test_filesystem_write_detection() -> None:
    node = make_node("orders.save", "def save():\n    open('out.txt', 'w')\n")
    caps = _capabilities(node)
    assert Capability.FILESYSTEM_WRITE in caps
    assert Capability.FILESYSTEM_READ not in caps


def test_filesystem_read_detection() -> None:
    node = make_node("orders.load", "def load():\n    open('in.txt', 'r')\n")
    caps = _capabilities(node)
    assert Capability.FILESYSTEM_READ in caps
    assert Capability.FILESYSTEM_WRITE not in caps


def test_environment_and_credential_access_detection() -> None:
    node = make_node("orders.auth", "def auth():\n    token = os.environ['API_TOKEN']\n")
    caps = _capabilities(node)
    assert Capability.ENVIRONMENT_ACCESS in caps
    assert Capability.CREDENTIAL_ACCESS in caps


def test_environment_access_without_credential_hint() -> None:
    node = make_node("orders.get_region", "def get_region():\n    return os.environ['REGION']\n")
    caps = _capabilities(node)
    assert Capability.ENVIRONMENT_ACCESS in caps
    assert Capability.CREDENTIAL_ACCESS not in caps


def test_dynamic_execution_detection() -> None:
    node = make_node("orders.run", "def run(expr):\n    eval(expr)\n")
    caps = _capabilities(node)
    assert Capability.DYNAMIC_CODE_EXECUTION in caps


def test_database_access_detection() -> None:
    node = make_node("orders.connect_db", "def connect_db():\n    sqlite3.connect('data.db')\n")
    caps = _capabilities(node)
    assert Capability.DATABASE_ACCESS in caps


def test_multiple_capabilities_in_one_target() -> None:
    node = make_node(
        "orders.process",
        "def process():\n"
        "    subprocess.run(['echo'])\n"
        "    requests.post('https://api.example.com')\n"
        "    open('log.txt', 'w')\n",
    )
    caps = _capabilities(node)
    assert Capability.PROCESS_EXECUTION in caps
    assert Capability.NETWORK_ACCESS in caps
    assert Capability.FILESYSTEM_WRITE in caps


def test_unknown_ambiguous_call_is_flagged_not_ignored() -> None:
    node = make_node("orders.dispatch", "def dispatch():\n    some_unrecognized_plugin_hook()\n")
    caps = _capabilities(node)
    assert Capability.UNKNOWN_EXTERNAL_EFFECT in caps


def test_known_safe_builtins_produce_no_signal() -> None:
    node = make_node("orders.total", "def total(items):\n    return sum(len(str(x)) for x in sorted(items))\n")
    signals = detect_capabilities(node)
    assert signals == []


def test_missing_lexical_representation_is_flagged_unknown() -> None:
    node = make_node("orders.mystery", "")
    caps = _capabilities(node)
    assert caps == {Capability.UNKNOWN_EXTERNAL_EFFECT}


def test_unparseable_source_is_flagged_unknown_not_raised() -> None:
    node = make_node("orders.broken", "def broken(:\n")
    signals = detect_capabilities(node)  # must not raise
    assert {s.capability for s in signals} == {Capability.UNKNOWN_EXTERNAL_EFFECT}


def test_every_signal_carries_evidence() -> None:
    node = make_node("orders.run_cmd", "def run_cmd():\n    subprocess.run(['ls'])\n")
    for signal in detect_capabilities(node):
        assert signal.evidence
        assert signal.matched_pattern

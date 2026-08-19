"""
PLAN.md Milestone 3, Phase 3.1 -- Capability / Risk Detection.

This module answers exactly one question: "what potentially relevant
capabilities can we identify from this node's source text?" It has zero
knowledge of SafetyClass, policy, or execution -- that separation is
deliberate (Capability Detection != Policy Evaluation != Execution). It also
performs no execution of any kind: it only calls `ast.parse()` on text
already captured by Phase 2.1, never imports/runs the target code.

Detection is a fixed table of known dotted-call patterns (`subprocess.run`,
`socket.socket`, `requests.post`, ...) plus one deliberate catch-all: any
call this table doesn't recognize, and whose base name isn't a small
allowlist of clearly-inert builtins, becomes UNKNOWN_EXTERNAL_EFFECT. This
is what keeps "we didn't detect anything dangerous" from silently meaning
"we looked at everything and it's fine" -- most real-world calls to
functions this table has never heard of end up as an explicit UNKNOWN
signal, not silence.

Known, explicit limitations (not oversights):
  - Detection is per-node, from that node's own lexical_representation only.
    A function's capabilities are judged from its own body; capabilities of
    functions it calls are that callee's own concern when IT is analyzed,
    not inherited here.
  - Dotted-chain matching is syntactic (`subprocess.run(...)`) -- it will
    miss the same call reached through indirection (`f = subprocess.run;
    f(...)`), a re-exported alias, or a wrapper function with a misleading
    name. This is exactly why detection output is a set of *signals*, not a
    safety proof.
  - EXTERNAL_NETWORK_ACCESS is only emitted when a literal URL argument is
    present and doesn't look local (`localhost`/`127.0.0.1`/`0.0.0.0`) --
    never guessed when the URL is computed/dynamic.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from veyra.vbg import Capability, Node

_SAFE_BUILTINS = {
    "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "range", "sorted", "enumerate", "zip", "map", "filter", "print",
    "isinstance", "hasattr", "getattr", "setattr", "min", "max", "sum",
    "abs", "round", "any", "all", "repr", "format", "super", "type",
    "frozenset", "reversed", "iter", "next", "vars", "id",
}

_PROCESS_EXEC_EXACT = {
    "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.Popen",
}
_OS_PROCESS_EXEC_PREFIXES = ("os.system", "os.popen", "os.exec", "os.spawn")
_SOCKET_EXACT = {"socket.socket", "socket.create_connection"}
_NETWORK_EXACT = {
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "requests.request", "requests.head", "requests.patch",
    "urllib.request.urlopen", "httpx.get", "httpx.post", "httpx.put",
    "httpx.delete", "httpx.request",
}
_DYNAMIC_EXEC_EXACT = {"eval", "exec", "compile", "__import__"}
_DB_PREFIXES = (
    "sqlite3.connect", "psycopg2.connect", "pymongo.MongoClient",
    "sqlalchemy.create_engine", "redis.Redis", "redis.StrictRedis",
)
_NATIVE_PREFIXES = ("ctypes.",)
_ENV_ACCESS_EXACT = {"os.getenv", "os.environ.get"}
_FS_WRITE_SUFFIXES = (
    ".write_text", ".write_bytes", ".unlink", ".rmdir", ".mkdir",
    ".rename", ".replace", ".touch",
)
_FS_READ_SUFFIXES = (".read_text", ".read_bytes")
_CREDENTIAL_HINTS = ("token", "key", "secret", "password", "credential", "auth")
_LOCAL_HOST_HINTS = ("localhost", "127.0.0.1", "0.0.0.0")


@dataclass(frozen=True)
class CapabilitySignal:
    capability: Capability
    evidence: str
    matched_pattern: str


def detect_capabilities(node: Node) -> list[CapabilitySignal]:
    """Pure: no VBGStore access, no execution. Returns [] only when the
    node's body was actually inspected and truly nothing matched (see
    resolve_safety_class() in policy.py for why that still doesn't mean
    SAFE)."""
    if not node.lexical_representation:
        return [
            CapabilitySignal(
                Capability.UNKNOWN_EXTERNAL_EFFECT,
                f"no lexical_representation available for {node.entity_id} -- capabilities could not be inspected",
                "no_source",
            )
        ]
    try:
        tree = ast.parse(node.lexical_representation)
    except SyntaxError as exc:
        return [
            CapabilitySignal(
                Capability.UNKNOWN_EXTERNAL_EFFECT,
                f"source segment for {node.entity_id} could not be parsed in isolation: {exc}",
                "parse_error",
            )
        ]

    signals: list[CapabilitySignal] = []
    for child in ast.walk(tree):
        if isinstance(child, ast.Call):
            signals.extend(_classify_call(child))
        elif isinstance(child, ast.Subscript):
            signals.extend(_classify_subscript(child))
    return signals


def _dotted_chain(expr: ast.expr) -> str | None:
    parts: list[str] = []
    node: ast.expr = expr
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _signal(capability: Capability, matched_pattern: str, lineno: int) -> CapabilitySignal:
    return CapabilitySignal(
        capability=capability,
        evidence=f"call to `{matched_pattern}` at line {lineno}",
        matched_pattern=matched_pattern,
    )


def _mentions_credential_hint_str(value: str) -> bool:
    lowered = value.lower()
    return any(hint in lowered for hint in _CREDENTIAL_HINTS)


def _string_args(call: ast.Call) -> list[str]:
    values = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    values.extend(
        kw.value.value for kw in call.keywords
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)
    )
    return values


def _looks_external(call: ast.Call) -> bool | None:
    """True: literal URL evidence suggests an external host. False: literal
    URL evidence suggests a local host. None: no usable literal evidence --
    no EXTERNAL_NETWORK_ACCESS signal is emitted in that case."""
    url: str | None = None
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        url = call.args[0].value
    for kw in call.keywords:
        if kw.arg == "url" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            url = kw.value.value
    if url is None:
        return None
    lowered = url.lower()
    if any(hint in lowered for hint in _LOCAL_HOST_HINTS):
        return False
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return True
    return None


def _classify_open(call: ast.Call, lineno: int) -> CapabilitySignal:
    mode: str | None = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str):
        mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            mode = kw.value.value
    if mode and any(flag in mode for flag in ("w", "a", "x", "+")):
        return _signal(Capability.FILESYSTEM_WRITE, "open(...)", lineno)
    return _signal(Capability.FILESYSTEM_READ, "open(...)", lineno)


def _classify_call(call: ast.Call) -> list[CapabilitySignal]:
    chain = _dotted_chain(call.func)
    if chain is None:
        return []  # call target isn't a statically-resolvable dotted name

    lineno = call.lineno
    signals: list[CapabilitySignal] = []

    if chain in _PROCESS_EXEC_EXACT:
        signals.append(_signal(Capability.PROCESS_EXECUTION, chain, lineno))
        signals.append(_signal(Capability.SUBPROCESS_EXECUTION, chain, lineno))
    elif chain.startswith(_OS_PROCESS_EXEC_PREFIXES):
        signals.append(_signal(Capability.PROCESS_EXECUTION, chain, lineno))
    elif chain in _SOCKET_EXACT:
        signals.append(_signal(Capability.SOCKET_ACCESS, chain, lineno))
        signals.append(_signal(Capability.NETWORK_ACCESS, chain, lineno))
    elif chain in _NETWORK_EXACT:
        signals.append(_signal(Capability.NETWORK_ACCESS, chain, lineno))
        if _looks_external(call):
            signals.append(_signal(Capability.EXTERNAL_NETWORK_ACCESS, chain, lineno))
    elif chain in _DYNAMIC_EXEC_EXACT:
        signals.append(_signal(Capability.DYNAMIC_CODE_EXECUTION, chain, lineno))
    elif chain.startswith(_DB_PREFIXES):
        signals.append(_signal(Capability.DATABASE_ACCESS, chain, lineno))
    elif chain.startswith(_NATIVE_PREFIXES):
        signals.append(_signal(Capability.NATIVE_CODE_ACCESS, chain, lineno))
    elif chain in _ENV_ACCESS_EXACT:
        signals.append(_signal(Capability.ENVIRONMENT_ACCESS, chain, lineno))
        if any(_mentions_credential_hint_str(v) for v in _string_args(call)):
            signals.append(_signal(Capability.CREDENTIAL_ACCESS, chain, lineno))
    elif chain == "open":
        signals.append(_classify_open(call, lineno))
    elif chain.endswith(_FS_WRITE_SUFFIXES):
        signals.append(_signal(Capability.FILESYSTEM_WRITE, chain, lineno))
    elif chain.endswith(_FS_READ_SUFFIXES):
        signals.append(_signal(Capability.FILESYSTEM_READ, chain, lineno))
    else:
        base = chain.split(".")[0]
        if base not in _SAFE_BUILTINS:
            signals.append(_signal(Capability.UNKNOWN_EXTERNAL_EFFECT, chain, lineno))

    return signals


def _classify_subscript(node: ast.Subscript) -> list[CapabilitySignal]:
    chain = _dotted_chain(node.value)
    if chain != "os.environ":
        return []

    lineno = node.lineno
    signals = [_signal(Capability.ENVIRONMENT_ACCESS, "os.environ[...]", lineno)]

    key = node.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str) and _mentions_credential_hint_str(key.value):
        signals.append(_signal(Capability.CREDENTIAL_ACCESS, f"os.environ[{key.value!r}]", lineno))
    return signals

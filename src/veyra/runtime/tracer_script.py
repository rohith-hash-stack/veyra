"""
PLAN.md Milestone 3, Phase 3.5 -- the code that runs *inside* the Docker
sandbox (Phase 3.2) to actually invoke a Scenario's target function and
trace it. Stdlib-only by construction (`sys.settrace`, no `coverage.py` or
any other third-party instrumentation dependency).

Tracing is scoped to code whose `co_filename` is under `/workspace` (the
mounted, read-only repository) -- this is what keeps the trace to "this
repository's own call graph" rather than every stdlib/library frame the
interpreter touches. A call into anything outside `/workspace` is recorded
once, as a single `external_interaction` event, and NOT traced further
inside (returning None from the trace function for that frame) -- this is
deliberately shallow: it proves an external boundary was crossed without
pretending to observe what happened on the other side of it.

Entity identity for a traced frame is `f"{module.__name__}.{code.co_qualname}"`
-- `co_qualname` (Python 3.11+) already renders `Class.method` for bound
calls, so this lines up exactly with the extractor's own
`f"{parent_id}.{name}"` entity_id convention with no extra bookkeeping.

Only module-level function targets are ever attempted (Phase 3.4 never
marks a bound method executable, so there is no class-instantiation logic
here at all, not even a stub for it). Argument values are the trivial
zero-literal for each primitive type tag the caller already decided was
synthesizable -- see engine.py's docstring for why this is deliberately not
meaningful input-space exploration.
"""

from __future__ import annotations

TRACER_SOURCE = r'''
import importlib.util
import json
import sys
import time

sys.path.insert(0, "/workspace")

_PRIMITIVE_LITERALS = {"str": "", "int": 0, "float": 0.0, "bool": False, "bytes": b""}


def _load_module(module_id, file_path):
    spec = importlib.util.spec_from_file_location(module_id, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_id] = module
    spec.loader.exec_module(module)
    return module


def main():
    with open("/output/spec.json", "r", encoding="utf-8") as f:
        spec = json.load(f)

    events = []
    start_time = None

    def tracer(frame, event, arg):
        code = frame.f_code
        offset = time.perf_counter() - start_time if start_time is not None else 0.0

        if event == "call":
            if not code.co_filename.startswith("/workspace"):
                events.append({
                    "kind": "external_interaction", "entity_id": None,
                    "qualname": "{}:{}".format(code.co_filename, code.co_name),
                    "offset_seconds": offset,
                })
                return None  # do not trace further inside external/stdlib code
            module_name = frame.f_globals.get("__name__")
            qualname = getattr(code, "co_qualname", code.co_name)
            entity_id = "{}.{}".format(module_name, qualname) if module_name else None
            events.append({"kind": "call", "entity_id": entity_id, "qualname": qualname, "offset_seconds": offset})
            return tracer

        # only /workspace frames are ever given this function as their own
        # local tracer (external frames returned None above), so return/
        # exception events below are always for a /workspace frame.
        module_name = frame.f_globals.get("__name__")
        qualname = getattr(code, "co_qualname", code.co_name)
        entity_id = "{}.{}".format(module_name, qualname) if module_name else None

        if event == "return":
            events.append({"kind": "return", "entity_id": entity_id, "qualname": qualname, "offset_seconds": offset})
        elif event == "exception":
            exc_type, exc_value, _ = arg
            events.append({
                "kind": "exception", "entity_id": entity_id, "qualname": qualname,
                "offset_seconds": offset,
                "exception_type": exc_type.__name__, "exception_message": str(exc_value)[:500],
            })
        return tracer

    result = {
        "status": "COMPLETED", "return_repr": None,
        "exception_type": None, "exception_message": None,
        "duration_seconds": 0.0, "events": [],
    }

    try:
        module = _load_module(spec["module_id"], "/workspace/" + spec["module_path"])
        target_callable = getattr(module, spec["function_name"])
    except Exception as exc:
        result["status"] = "EXCEPTION"
        result["exception_type"] = type(exc).__name__
        result["exception_message"] = "could not load target: {}: {}".format(type(exc).__name__, exc)
        with open("/output/trace.json", "w", encoding="utf-8") as f:
            json.dump(result, f)
        return

    kwargs = {name: _PRIMITIVE_LITERALS[tag] for name, tag in spec["kwargs_type_tags"].items()}

    start_time = time.perf_counter()
    sys.settrace(tracer)
    try:
        value = target_callable(**kwargs)
        result["return_repr"] = repr(value)[:500]
    except BaseException as exc:
        result["status"] = "EXCEPTION"
        result["exception_type"] = type(exc).__name__
        result["exception_message"] = str(exc)[:500]
    finally:
        sys.settrace(None)
    result["duration_seconds"] = time.perf_counter() - start_time
    result["events"] = events

    with open("/output/trace.json", "w", encoding="utf-8") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
'''

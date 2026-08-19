"""
PLAN.md Milestone 3, Phase 3.3a -- the code that actually runs *inside* the
Docker sandbox (Phase 3.2) to execute discovered tests. Stdlib-only by
construction (no `pytest`, no third-party test runner) -- this is exactly
what lets 3.3a harness a "no third-party dependency" repository's test suite
without needing the dependency-installation pipeline install_policy.py
deliberately declines to build yet.

unittest.TestCase-based tests run through unittest's own machinery (each
test method is instantiated and run individually, matching how the harness
addresses one test at a time). Bare pytest-style `def test_x(): assert ...`
functions are called directly with their AssertionError caught by hand,
since unittest's loader does not discover those at all.

Reads its work order from /output/spec.json (written by the harness manager
before the container starts) and writes /output/results.json (read back by
the manager after the container exits) -- structured JSON in and out, not
stdout scraping, matching how Phase 3.2's tests already prove content
written to the output mount lands back on the host.
"""

from __future__ import annotations

RUNNER_SOURCE = r'''
import importlib.util
import json
import sys
import time
import unittest

sys.path.insert(0, "/workspace")


def _load_module(module_id, file_path):
    spec = importlib.util.spec_from_file_location(module_id, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_id] = module
    spec.loader.exec_module(module)
    return module


def _run_function(entity_id, func):
    start = time.perf_counter()
    try:
        func()
    except AssertionError as exc:
        return {
            "entity_id": entity_id, "status": "FAIL",
            "message": str(exc) or "AssertionError",
            "duration_seconds": time.perf_counter() - start,
        }
    except Exception as exc:
        return {
            "entity_id": entity_id, "status": "ERROR",
            "message": "{}: {}".format(type(exc).__name__, exc),
            "duration_seconds": time.perf_counter() - start,
        }
    return {"entity_id": entity_id, "status": "PASS", "message": None,
            "duration_seconds": time.perf_counter() - start}


def _run_unittest_case(entity_id, cls, method_name):
    start = time.perf_counter()
    try:
        instance = cls(method_name)
    except Exception as exc:
        return {
            "entity_id": entity_id, "status": "ERROR",
            "message": "could not instantiate test case: {}".format(exc),
            "duration_seconds": 0.0,
        }
    result = unittest.TestResult()
    instance.run(result)
    duration = time.perf_counter() - start
    if result.wasSuccessful():
        return {"entity_id": entity_id, "status": "PASS", "message": None, "duration_seconds": duration}
    if result.failures:
        return {"entity_id": entity_id, "status": "FAIL", "message": result.failures[0][1], "duration_seconds": duration}
    return {
        "entity_id": entity_id, "status": "ERROR",
        "message": result.errors[0][1] if result.errors else "unknown unittest error",
        "duration_seconds": duration,
    }


def main():
    with open("/output/spec.json", "r", encoding="utf-8") as f:
        spec = json.load(f)

    results = []
    modules = {}
    for item in spec:
        module_id = item["module_id"]
        file_path = "/workspace/" + item["module_path"]
        entity_id = item["entity_id"]
        try:
            if module_id not in modules:
                modules[module_id] = _load_module(module_id, file_path)
            module = modules[module_id]
        except Exception as exc:
            results.append({
                "entity_id": entity_id, "status": "ERROR",
                "message": "module import failed: {}: {}".format(type(exc).__name__, exc),
                "duration_seconds": 0.0,
            })
            continue

        try:
            if item["class_name"]:
                cls = getattr(module, item["class_name"])
                results.append(_run_unittest_case(entity_id, cls, item["function_name"]))
            else:
                func = getattr(module, item["function_name"])
                results.append(_run_function(entity_id, func))
        except Exception as exc:
            results.append({
                "entity_id": entity_id, "status": "ERROR",
                "message": "harness could not invoke test: {}: {}".format(type(exc).__name__, exc),
                "duration_seconds": 0.0,
            })

    with open("/output/results.json", "w", encoding="utf-8") as f:
        json.dump({"results": results}, f)


if __name__ == "__main__":
    main()
'''

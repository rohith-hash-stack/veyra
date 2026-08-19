"""
PLAN.md Milestone 3, Phase 3.4 -- pure call-signature introspection,
re-parsing a Node's own lexical_representation via `ast` (the same technique
veyra.safety.capabilities uses on the exact same field) to answer "what
would it take to call this function/method directly, with no arguments
beyond what can already be synthesized?" No execution, no VBGStore access.

Deliberately narrow for this slice: only a small primitive-annotation
allowlist (str/int/float/bool/bytes) or an existing default value counts as
"synthesizable" -- this phase only decides whether a candidate scenario is
plannable at all, it does not synthesize actual values (that is Phase
3.3b's job, restricted to the SAFE-classified subset per D2). A bound
method (`node.type == "Method"`) is never synthesizable in this slice --
there is no constructor/fixture strategy yet to obtain an instance to call
it on.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from veyra.vbg import Node

_SYNTHESIZABLE_ANNOTATIONS = {"str", "int", "float", "bool", "bytes"}


@dataclass(frozen=True)
class Parameter:
    name: str
    annotation: str | None
    has_default: bool
    synthesizable: bool


@dataclass(frozen=True)
class Signature:
    parameters: tuple[Parameter, ...]
    is_bound_method: bool
    has_var_positional: bool
    has_var_keyword: bool


def _annotation_name(expr: ast.expr | None) -> str | None:
    if expr is None:
        return None
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value  # a string-quoted forward-reference annotation, e.g. "int"
    return None  # subscripted generics, attributes, unions, ... not resolved in this slice


def _make_parameter(name: str, annotation: str | None, has_default: bool) -> Parameter:
    synthesizable = has_default or annotation in _SYNTHESIZABLE_ANNOTATIONS
    return Parameter(name=name, annotation=annotation, has_default=has_default, synthesizable=synthesizable)


def extract_signature(node: Node) -> Signature | None:
    """Returns None when there is no source to introspect at all, or it
    doesn't parse as a function -- callers map that directly to
    NO_SOURCE_AVAILABLE."""
    if not node.lexical_representation:
        return None
    try:
        tree = ast.parse(node.lexical_representation)
    except SyntaxError:
        return None

    func_def = next(
        (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
        None,
    )
    if func_def is None:
        return None

    is_bound_method = node.type == "Method"
    args = func_def.args
    positional = [*args.posonlyargs, *args.args]
    boundary = len(positional) - len(args.defaults)

    parameters: list[Parameter] = []
    for index, arg in enumerate(positional):
        if is_bound_method and index == 0 and arg.arg in ("self", "cls"):
            continue  # the bound receiver, not a real call input
        parameters.append(_make_parameter(arg.arg, _annotation_name(arg.annotation), index >= boundary))

    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parameters.append(_make_parameter(arg.arg, _annotation_name(arg.annotation), default is not None))

    return Signature(
        parameters=tuple(parameters),
        is_bound_method=is_bound_method,
        has_var_positional=args.vararg is not None,
        has_var_keyword=args.kwarg is not None,
    )

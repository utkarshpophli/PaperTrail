"""Restricted-grammar formula validator + evaluator for Interactive learning
content (docs/SECURITY.md: "restricted declarative grammar, evaluated on a
constrained AST -- never eval, never arbitrary JS", and CLAUDE.md's parallel
requirement that no code extracted from a paper is ever executed).

A parallel agent is porting this exact grammar to TypeScript for the
frontend playground -- both must enforce the identical whitelist:

- numeric literals (int/float), named parameter references
- binary ``+ - * / ** %``, unary ``-``/``+``, parentheses
- functions ONLY: ``sqrt, abs, min, max, log, exp, sin, cos, tan, floor,
  ceil, round`` (``min``/``max`` take 2+ args, every other function takes
  exactly 1)
- nothing else: no comparisons, no boolean ops, no conditionals, no
  string/list/dict/set literals, no attribute access, no subscripting, no
  lambda, no walrus, no f-strings, no starred/keyword args.

Two-phase design, matching CLAUDE.md's "never eval, even after validating
it's safe":

1. ``validate_formula`` -- ``ast.parse`` then a default-deny walk that
   allows ONLY the node types/operators/functions above. Every ``ast.Name``
   is resolved by position: a callee-position name must be a whitelisted
   function, an operand-position name must be a declared parameter -- never
   both, never neither.
2. ``evaluate_formula`` -- a hand-written recursive evaluator that walks the
   *already-validated* tree node-by-node. It never calls ``eval``/``exec``/
   ``compile`` on the formula string or the tree, no matter how thoroughly
   step 1 proved it safe.

All arithmetic is float (never Python's arbitrary-precision int) -- this is
what makes an exponent tower like ``2**2**2**2**2**2**2**2**2**2`` cheap
(overflows to ``inf``, caught by ``_check_result`` below) instead of a
CPU-hanging bignum computation.
"""

import ast
import math
from collections.abc import Callable, Iterable, Mapping

from app.evidence.exceptions import FormulaEvaluationError, FormulaValidationError

# Picked to comfortably fit a real slider-formula (well under typical
# expression lengths) while making a pathological input cheap to reject
# before it's even parsed.
MAX_FORMULA_LENGTH = 500

# Picked well above any formula a human would plausibly write (a handful of
# terms nests 3-5 deep) but low enough to bound this module's own recursion
# in both validate_formula's walk and evaluate_formula's evaluation to a
# trivial, fixed stack depth -- this is the recursion-based DoS guard, not
# just a style preference.
MAX_AST_DEPTH = 20

# name -> (min_args, max_args | None for unbounded)
_FUNCTIONS: dict[str, tuple[int, int | None]] = {
    "sqrt": (1, 1),
    "abs": (1, 1),
    "log": (1, 1),
    "exp": (1, 1),
    "sin": (1, 1),
    "cos": (1, 1),
    "tan": (1, 1),
    "floor": (1, 1),
    "ceil": (1, 1),
    "round": (1, 1),
    "min": (2, None),
    "max": (2, None),
}

def _round_half_away_from_zero(x: float) -> float:
    # Security review LOW/MEDIUM: Python's builtin round() uses banker's
    # rounding (round(0.5)==0, round(2.5)==2) while JS's Math.round rounds
    # half-up (Math.round(0.5)===1) -- for a product whose premise is exact
    # traceability, a formula near a .5 boundary silently disagreeing between
    # "validated on the backend" and "evaluated live in the browser" is a
    # real integrity concern, not a rendering nit. Implementing the same
    # explicit rule on both sides (never relying on either builtin) makes
    # them match regardless of platform quirks.
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


def _mod(a: float, b: float) -> float:
    # Python's native % already matches the convention documented here
    # (sign follows the divisor); kept as an explicit named function so the
    # parity contract with formula-grammar.ts's _mod is visible at a glance
    # rather than an easy-to-miss lambda.
    return a % b


_UNARY_FUNCS: dict[str, Callable[[float], float]] = {
    "sqrt": math.sqrt,
    "abs": abs,
    "log": math.log,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": _round_half_away_from_zero,
}

_ALLOWED_BINOPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
    ast.Mod: _mod,
}

_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


def assert_parameter_names_allowed(names: Iterable[str]) -> None:
    """Design decision (adversarial case: a parameter literally named e.g.
    ``sqrt``): rejected at declaration time, not merely shadowed.

    Positionally, ``_validate_node``/``_evaluate`` would actually resolve
    such a collision unambiguously on their own -- a callee-position name is
    checked only against the function whitelist, an operand-position name
    only against declared parameters -- so the grammar itself has no
    ambiguity. It's refused anyway because a slider named the same as a
    function called in the same formula is a confusing UX, not because
    leaving it alone would be unsafe.
    """
    for name in names:
        if name in _FUNCTIONS:
            raise FormulaValidationError(
                f"Parameter name {name!r} collides with a whitelisted function name and is not allowed"
            )


def _check_paren_depth(formula: str) -> None:
    # Security review LOW: CPython's own AST collapses redundant parens
    # around a bare literal into a single Constant node with no wrapping AST
    # node -- e.g. "(" * 100 + "1" + ")" * 100 previously sailed through
    # _validate_node's depth counter untouched, since that counter only sees
    # real BinOp/UnaryOp/Call nesting. This was harmless in practice only
    # because MAX_FORMULA_LENGTH combined with CPython's own hardcoded
    # nested-parenthesis ceiling happened to catch it first -- an implicit
    # backstop, not the depth guard the code claimed to have. Checked here,
    # on the raw source, independent of what the AST does or doesn't retain
    # -- matches formula-grammar.ts's parser, which counts paren depth
    # explicitly as it consumes tokens.
    depth = 0
    for char in formula:
        if char == "(":
            depth += 1
            if depth > MAX_AST_DEPTH:
                raise FormulaValidationError(f"Formula exceeds max nesting depth of {MAX_AST_DEPTH}")
        elif char == ")":
            depth -= 1


def validate_formula(formula: str, parameter_names: frozenset[str]) -> ast.Expression:
    """Parses ``formula`` and walks it with a default-deny check: any AST
    node type, operator, or function not explicitly whitelisted raises
    ``FormulaValidationError`` -- including node types not called out
    explicitly above, since the walk allows-lists rather than deny-lists.
    Never evaluates anything; returns the parsed (and now trusted) tree for
    ``evaluate_formula`` to walk separately.
    """
    if not isinstance(formula, str) or not formula.strip():
        raise FormulaValidationError("Formula must be a non-empty string")
    if len(formula) > MAX_FORMULA_LENGTH:
        raise FormulaValidationError(f"Formula exceeds max length of {MAX_FORMULA_LENGTH} characters")
    _check_paren_depth(formula)
    try:
        tree = ast.parse(formula, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        # RecursionError can surface from CPython's own parser on a
        # pathologically nested-but-short input (e.g. many nested
        # parens/unary ops) -- converted here into our own typed error
        # rather than ever propagating a raw interpreter crash.
        raise FormulaValidationError(f"Formula could not be parsed: {exc}") from exc
    _validate_node(tree.body, parameter_names, depth=0)
    return tree


def _validate_node(node: ast.AST, parameter_names: frozenset[str], depth: int) -> None:
    if depth > MAX_AST_DEPTH:
        raise FormulaValidationError(f"Formula exceeds max nesting depth of {MAX_AST_DEPTH}")

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaValidationError(f"Disallowed literal type: {type(node.value).__name__}")
        return

    if isinstance(node, ast.Name):
        # Operand position only -- a callee-position Name is handled
        # entirely inside the ast.Call branch below and never reaches here.
        if node.id not in parameter_names:
            raise FormulaValidationError(f"Unknown parameter reference: {node.id!r}")
        return

    if isinstance(node, ast.BinOp):
        if type(node.op) not in _ALLOWED_BINOPS:
            raise FormulaValidationError(f"Disallowed operator: {type(node.op).__name__}")
        _validate_node(node.left, parameter_names, depth + 1)
        _validate_node(node.right, parameter_names, depth + 1)
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise FormulaValidationError(f"Disallowed unary operator: {type(node.op).__name__}")
        _validate_node(node.operand, parameter_names, depth + 1)
        return

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise FormulaValidationError(
                "Function calls must use a plain whitelisted name (e.g. 'sqrt(x)'), never attribute access"
            )
        func_name = node.func.id
        if func_name not in _FUNCTIONS:
            raise FormulaValidationError(f"Disallowed function: {func_name!r}")
        if node.keywords:
            raise FormulaValidationError("Keyword arguments are not allowed in function calls")
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            raise FormulaValidationError("Starred/unpacked arguments are not allowed in function calls")
        min_args, max_args = _FUNCTIONS[func_name]
        arg_count = len(node.args)
        if arg_count < min_args or (max_args is not None and arg_count > max_args):
            expected = f"{min_args}+" if max_args is None else (str(min_args) if min_args == max_args else f"{min_args}-{max_args}")
            raise FormulaValidationError(f"{func_name}() called with {arg_count} argument(s); expected {expected}")
        for arg in node.args:
            _validate_node(arg, parameter_names, depth + 1)
        return

    raise FormulaValidationError(f"Disallowed syntax: {type(node).__name__}")


def evaluate_formula(tree: ast.Expression, param_values: Mapping[str, float]) -> float:
    """Hand-written recursive evaluator over an *already-validated* tree
    (never the raw formula string, never ``eval``/``exec``/``compile``).
    Raises ``FormulaEvaluationError`` -- a defined sentinel exception, never
    a raw Python exception -- for division by zero, a domain error
    (``sqrt``/``log`` of an out-of-domain value), overflow, or a result that
    is NaN/Infinity/complex.
    """
    return _evaluate(tree.body, param_values)


def _evaluate(node: ast.AST, param_values: Mapping[str, float]) -> float:
    if isinstance(node, ast.Constant):
        return float(node.value)

    if isinstance(node, ast.Name):
        if node.id not in param_values:
            raise FormulaEvaluationError(f"Missing value for parameter {node.id!r}")
        return float(param_values[node.id])

    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand, param_values)
        return _check_result(operand if isinstance(node.op, ast.UAdd) else -operand)

    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, param_values)
        right = _evaluate(node.right, param_values)
        op = _ALLOWED_BINOPS[type(node.op)]  # already validated -- must be present
        try:
            result = op(left, right)
        except (ZeroDivisionError, OverflowError, ValueError) as exc:
            raise FormulaEvaluationError(f"Undefined result: {exc}") from exc
        return _check_result(result)

    if isinstance(node, ast.Call):
        func_name = node.func.id  # type: ignore[union-attr]  # already validated to be an ast.Name
        args = [_evaluate(arg, param_values) for arg in node.args]
        try:
            if func_name in ("min", "max"):
                result = (min if func_name == "min" else max)(args)
            else:
                result = _UNARY_FUNCS[func_name](args[0])
        except (ValueError, OverflowError) as exc:
            raise FormulaEvaluationError(f"Undefined result: {exc}") from exc
        return _check_result(result)

    # Unreachable if the tree actually came from validate_formula, but a
    # defined error here (never a raw AttributeError/crash) protects any
    # future caller that evaluates a tree without validating it first.
    raise FormulaEvaluationError(f"Unsupported node during evaluation: {type(node).__name__}")


def _check_result(value: complex | float | int) -> float:
    if isinstance(value, complex):
        raise FormulaEvaluationError("Formula produced a complex result, which is not supported")
    result = float(value)
    if math.isnan(result) or math.isinf(result):
        raise FormulaEvaluationError("Formula produced an undefined result (NaN or Infinity)")
    return result

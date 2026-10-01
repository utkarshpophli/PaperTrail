"""Unit tests for the restricted-grammar formula validator/evaluator
(app.evidence.formula) -- SECURITY.md's "restricted declarative grammar,
evaluated on a constrained AST -- never eval, never arbitrary JS"
requirement. Pure logic, no DB/provider needed.

Covers the adversarial cases this phase's task brief calls out explicitly:
deeply nested expression, an exponent tower that must not hang, division by
zero, an undeclared parameter, a non-whitelisted function, attribute access,
subscripting, a lambda, a comparison, an over-length formula, and a
parameter name that shadows a whitelisted function name.
"""

import ast

import pytest

from app.evidence.exceptions import FormulaEvaluationError, FormulaValidationError
from app.evidence.formula import (
    MAX_AST_DEPTH,
    MAX_FORMULA_LENGTH,
    assert_parameter_names_allowed,
    evaluate_formula,
    validate_formula,
)


def _validated(formula: str, params: frozenset[str] = frozenset()) -> ast.Expression:
    return validate_formula(formula, params)


# ---- happy path -------------------------------------------------------


def test_basic_arithmetic_validates_and_evaluates() -> None:
    tree = _validated("a * b + 1", frozenset({"a", "b"}))
    assert evaluate_formula(tree, {"a": 2.0, "b": 3.0}) == 7.0


def test_whitelisted_functions_validate_and_evaluate() -> None:
    tree = _validated("sqrt(x) + min(y, 2, 3) + max(y, 2, 3)", frozenset({"x", "y"}))
    result = evaluate_formula(tree, {"x": 9.0, "y": 5.0})
    assert result == pytest.approx(3.0 + 2.0 + 5.0)


def test_unary_and_parentheses_validate_and_evaluate() -> None:
    tree = _validated("-(x + 1) * -1", frozenset({"x"}))
    assert evaluate_formula(tree, {"x": 4.0}) == 5.0


def test_modulo_and_power_validate_and_evaluate() -> None:
    tree = _validated("x ** 2 % 5", frozenset({"x"}))
    assert evaluate_formula(tree, {"x": 4.0}) == 1.0


# ---- adversarial cases --------------------------------------------------


def test_deeply_nested_expression_rejected_by_depth_cap_not_recursion_error() -> None:
    # Nested unary-minus-in-parens -- genuine AST nesting (plain redundant
    # parens alone collapse to a single Constant node in CPython's own
    # parser and carry no extra depth).
    depth = MAX_AST_DEPTH + 5
    formula = "-(" * depth + "1" + ")" * depth
    with pytest.raises(FormulaValidationError, match="nesting depth"):
        validate_formula(formula, frozenset())


def test_exponent_tower_does_not_hang_and_overflows_cleanly() -> None:
    # 2**2**2**2**2**2**2**2**2**2 -- as Python's arbitrary-precision int
    # this is a CPU-hanging bignum; as float it overflows to inf quickly,
    # which evaluate_formula must convert to a defined exception, never a
    # hang and never a silently-returned inf.
    formula = "2**2**2**2**2**2**2**2**2**2"
    tree = validate_formula(formula, frozenset())
    with pytest.raises(FormulaEvaluationError, match="undefined result|Undefined result"):
        evaluate_formula(tree, {})


def test_division_by_zero_raises_formula_evaluation_error() -> None:
    tree = validate_formula("1 / x", frozenset({"x"}))
    with pytest.raises(FormulaEvaluationError):
        evaluate_formula(tree, {"x": 0.0})


def test_undeclared_parameter_rejected() -> None:
    with pytest.raises(FormulaValidationError, match="Unknown parameter"):
        validate_formula("x + y", frozenset({"x"}))


@pytest.mark.parametrize("formula", ["open('x')", "__import__('os')", "eval('1')"])
def test_non_whitelisted_function_rejected(formula: str) -> None:
    with pytest.raises(FormulaValidationError, match="Disallowed function"):
        validate_formula(formula, frozenset())


def test_attribute_access_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("x.__class__", frozenset({"x"}))


def test_subscripting_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("x[0]", frozenset({"x"}))


def test_lambda_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("(lambda x: x)(1)", frozenset())


def test_comparison_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("x > 0", frozenset({"x"}))


def test_boolean_op_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("x and y", frozenset({"x", "y"}))


def test_conditional_expression_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("x if x > 0 else 0", frozenset({"x"}))


def test_string_literal_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("'x'", frozenset())


def test_list_literal_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("[1, 2]", frozenset())


def test_walrus_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("(x := 1)", frozenset())


def test_fstring_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("f'{1}'", frozenset())


def test_starred_args_rejected() -> None:
    with pytest.raises(FormulaValidationError, match="Starred"):
        validate_formula("max(*args)", frozenset({"args"}))


def test_keyword_args_rejected() -> None:
    with pytest.raises(FormulaValidationError, match="Keyword"):
        validate_formula("round(x, ndigits=2)", frozenset({"x"}))


def test_wrong_arity_rejected() -> None:
    with pytest.raises(FormulaValidationError, match="argument"):
        validate_formula("sqrt(x, y)", frozenset({"x", "y"}))
    with pytest.raises(FormulaValidationError, match="argument"):
        validate_formula("min(x)", frozenset({"x"}))


def test_formula_over_length_cap_rejected() -> None:
    formula = "1 + " * (MAX_FORMULA_LENGTH // 4 + 5) + "1"
    assert len(formula) > MAX_FORMULA_LENGTH
    with pytest.raises(FormulaValidationError, match="max length"):
        validate_formula(formula, frozenset())


def test_empty_formula_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("", frozenset())


def test_bool_literal_rejected() -> None:
    with pytest.raises(FormulaValidationError):
        validate_formula("True", frozenset())


# ---- parameter name shadowing a whitelisted function name ---------------
# Design decision (documented in app.evidence.formula.assert_parameter_names_allowed):
# rejected at declaration time, not left as undefined/just-shadows behavior.


def test_parameter_name_shadowing_function_rejected_at_declaration() -> None:
    with pytest.raises(FormulaValidationError, match="collides"):
        assert_parameter_names_allowed(frozenset({"sqrt"}))


def test_grammar_itself_resolves_shadowed_name_unambiguously_by_position() -> None:
    """Even though a parameter named 'sqrt' is rejected up front (previous
    test), the underlying grammar resolution is documented as unambiguous by
    position -- verified directly here so that guarantee has its own
    regression coverage independent of the declaration-time policy."""
    tree = validate_formula("sqrt(sqrt)", frozenset({"sqrt"}))
    assert evaluate_formula(tree, {"sqrt": 9.0}) == 3.0


# ---- cross-implementation parity (security review LOW/MEDIUM) -----------
# frontend/lib/formula-grammar.test.ts asserts these exact same values for
# its pythonStyleMod/roundHalfAwayFromZero -- not a shared test runner, but
# both sides pinned to the identical expected numbers closes the semantic
# mismatch the review found (JS-native % follows the dividend's sign,
# Math.round uses round-half-up; neither builtin is used anymore).


def test_modulo_matches_python_sign_convention_for_negative_operands() -> None:
    tree = _validated("x % 3", frozenset({"x"}))
    assert evaluate_formula(tree, {"x": -1.0}) == 2.0


def test_round_uses_half_away_from_zero_not_bankers_rounding() -> None:
    tree = _validated("round(x)", frozenset({"x"}))
    assert evaluate_formula(tree, {"x": 0.5}) == 1.0
    assert evaluate_formula(tree, {"x": 1.5}) == 2.0
    assert evaluate_formula(tree, {"x": 2.5}) == 3.0
    assert evaluate_formula(tree, {"x": -0.5}) == -1.0


# ---- paren-depth (security review LOW: AST collapses redundant parens) --


def test_deeply_parenthesized_literal_rejected_by_explicit_paren_scan() -> None:
    # CPython's AST collapses "(((1)))" into a single Constant with no
    # wrapping node, so _validate_node's depth counter alone never sees this
    # -- must be caught by the pre-parse scan on the raw source instead.
    formula = "(" * (MAX_AST_DEPTH + 1) + "1" + ")" * (MAX_AST_DEPTH + 1)
    with pytest.raises(FormulaValidationError, match="nesting depth"):
        validate_formula(formula, frozenset())


# ---- NaN/Infinity in parameter bounds (security review MEDIUM) ----------


def test_parameter_draft_rejects_nan_and_infinite_bounds() -> None:
    from app.evidence.schemas import InteractiveParameterDraft

    with pytest.raises(ValueError, match="finite"):
        InteractiveParameterDraft(name="x", label="X", min=0.0, max=10.0, step=float("nan"), default=5.0)
    with pytest.raises(ValueError, match="finite"):
        InteractiveParameterDraft(name="x", label="X", min=0.0, max=float("inf"), step=1.0, default=5.0)


def test_parameter_draft_rejects_non_identifier_name() -> None:
    from app.evidence.schemas import InteractiveParameterDraft

    with pytest.raises(ValueError):
        InteractiveParameterDraft(name="not a valid name!", label="X", min=0.0, max=10.0, step=1.0, default=5.0)

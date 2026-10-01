import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { evaluateFormula, FormulaParseError, isDefinedResult, parseFormula } from "./formula-grammar";

function evaluate(source: string, paramNames: string[], paramValues: Record<string, number>): number {
  return evaluateFormula(parseFormula(source, paramNames), paramValues);
}

describe("parseFormula / evaluateFormula -- happy path", () => {
  it("parses and evaluates arithmetic with parameters and whitelisted functions", () => {
    expect(evaluate("sqrt(x**2 + y**2)", ["x", "y"], { x: 3, y: 4 })).toBe(5);
    expect(evaluate("min(a, b, c)", ["a", "b", "c"], { a: 3, b: 1, c: 2 })).toBe(1);
    expect(evaluate("max(a, b)", ["a", "b"], { a: 3, b: 1 })).toBe(3);
    expect(evaluate("-x + 1", ["x"], { x: 5 })).toBe(-4);
  });

  it("applies -2**2 === -(2**2) precedence, matching the Python-style convention", () => {
    expect(evaluate("-2**2", [], {})).toBe(-4);
    expect(evaluate("2**-2", [], {})).toBe(0.25);
  });
});

describe("adversarial: deeply nested parens", () => {
  it("rejects nesting beyond the depth cap instead of overflowing the stack", () => {
    const deeplyNested = "(".repeat(200) + "1" + ")".repeat(200);
    expect(() => parseFormula(deeplyNested, [])).toThrow(FormulaParseError);
  });
});

describe("adversarial: huge exponent chain", () => {
  it("resolves a long right-associative ** chain cheaply, without hanging", () => {
    const start = Date.now();
    const result = evaluate("2**2**2**2**2**2**2**2**2**2", [], {});
    expect(Date.now() - start).toBeLessThan(1000);
    expect(result).toBe(Infinity);
  });
});

describe("adversarial: division by zero / undefined results", () => {
  it("returns Infinity/NaN instead of throwing, and isDefinedResult flags it", () => {
    expect(evaluate("1/x", ["x"], { x: 0 })).toBe(Infinity);
    expect(isDefinedResult(evaluate("1/x", ["x"], { x: 0 }))).toBe(false);
    expect(Number.isNaN(evaluate("0/x", ["x"], { x: 0 }))).toBe(true);
    expect(isDefinedResult(evaluate("x + 1", ["x"], { x: 3 }))).toBe(true);
  });
});

describe("adversarial: undeclared parameter reference", () => {
  it("rejects a parameter name not in the declared set", () => {
    expect(() => parseFormula("x + 1", [])).toThrow(FormulaParseError);
    expect(() => parseFormula("x + y", ["x"])).toThrow(FormulaParseError);
  });
});

describe("adversarial: non-whitelisted function call", () => {
  it("rejects a call to a function outside the whitelist", () => {
    expect(() => parseFormula("eval(1)", [])).toThrow(FormulaParseError);
    expect(() => parseFormula("pow(2, 3)", [])).toThrow(FormulaParseError);
  });
});

describe("adversarial: member access / computed access", () => {
  it("rejects both at tokenize time -- the tokenizer has no rule that accepts `.` outside a numeric literal or `[`/`]` at all", () => {
    expect(() => parseFormula("x.constructor", ["x"])).toThrow(FormulaParseError);
    expect(() => parseFormula("x[0]", ["x"])).toThrow(FormulaParseError);
  });
});

describe("adversarial: comparison operators", () => {
  it("rejects comparison and other non-grammar operators at tokenize time", () => {
    expect(() => parseFormula("x > 1", ["x"])).toThrow(FormulaParseError);
    expect(() => parseFormula("x == 1", ["x"])).toThrow(FormulaParseError);
    expect(() => parseFormula("x ? 1 : 2", ["x"])).toThrow(FormulaParseError);
  });
});

describe("adversarial: formula exceeding the length cap", () => {
  it("rejects a formula longer than 500 characters before tokenizing", () => {
    const tooLong = `${"1+".repeat(260)}1`;
    expect(tooLong.length).toBeGreaterThan(500);
    expect(() => parseFormula(tooLong, [])).toThrow(FormulaParseError);
  });
});

describe("adversarial: parameter name shadowing a whitelisted function name", () => {
  // Deliberate, documented behavior: call-ness is determined purely by a
  // trailing `(` in the grammar, not by name resolution. A bare identifier
  // that matches a declared parameter evaluates as that parameter; the same
  // name immediately followed by `(args)` is always parsed as a call to the
  // whitelisted function, never as "calling a parameter".
  it("evaluates a bare reference as the parameter, and call syntax as the whitelisted function, even when both share a name", () => {
    expect(evaluate("sqrt", ["sqrt"], { sqrt: 9 })).toBe(9);
    expect(evaluate("sqrt(9)", ["sqrt"], { sqrt: 1234 })).toBe(3);
  });
});

describe("adversarial: no eval / Function bridge in the source itself", () => {
  it("the module's code (comments stripped) never references eval, Function(, or new Function", () => {
    const source = readFileSync(join(__dirname, "formula-grammar.ts"), "utf-8");
    // Strip comments first -- this file's own security-intent comments
    // *name* eval/new Function/Function( in prose to explain what's
    // forbidden, which would otherwise false-positive against itself.
    const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    expect(code).not.toMatch(/\beval\s*\(/);
    expect(code).not.toMatch(/\bnew\s+Function\b/);
    expect(code).not.toMatch(/\bFunction\s*\(/);
  });
});

// ---- cross-implementation parity (security review LOW/MEDIUM) -----------
// backend/tests/evidence/test_formula.py asserts these exact same values
// for its Python-side _mod/_round_half_away_from_zero -- not a shared test
// runner, but both sides pinned to the identical expected numbers closes
// the semantic mismatch the review found: JS's native `%` follows the
// dividend's sign (Python follows the divisor's), and Math.round uses
// round-half-up (Python's builtin round() uses banker's rounding). Neither
// builtin is used anymore -- both sides implement the same explicit rule.

describe("cross-implementation parity: modulo and round", () => {
  it("modulo matches Python's sign convention for negative operands", () => {
    expect(evaluate("x % 3", ["x"], { x: -1 })).toBe(2);
  });

  it("round uses half-away-from-zero, not JS's native round-half-up or Python's banker's rounding", () => {
    expect(evaluate("round(x)", ["x"], { x: 0.5 })).toBe(1);
    expect(evaluate("round(x)", ["x"], { x: 1.5 })).toBe(2);
    expect(evaluate("round(x)", ["x"], { x: 2.5 })).toBe(3);
    expect(evaluate("round(x)", ["x"], { x: -0.5 })).toBe(-1);
  });
});

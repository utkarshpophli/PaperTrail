/**
 * A from-scratch tokenizer + recursive-descent parser + evaluator for the
 * Interactive learning content's restricted formula grammar.
 *
 * SECURITY: this module never calls `eval`, `new Function`, or the
 * `Function` constructor -- not on the raw formula string, not on anything
 * derived from it, even after validation. The backend independently
 * enforces the identical whitelist in Python (docs/SECURITY.md); the
 * frontend does not trust "the backend already validated this" as its only
 * control, since a user can edit query params / replay a captured request
 * and hit this module directly.
 *
 * Grammar (fixed, mirrors the backend's whitelist exactly):
 *   - numeric literals, named parameter references
 *   - binary + - * / ** %, unary - and +, parentheses
 *   - functions: sqrt abs min max log exp sin cos tan floor ceil round
 *     (min/max take 2+ args, all others take exactly 1)
 *   - nothing else: no comparisons, ternaries, string/array/object literals,
 *     member access, computed access, arrow functions, template literals
 */

export const FORMULA_FUNCTIONS = [
  "sqrt",
  "abs",
  "min",
  "max",
  "log",
  "exp",
  "sin",
  "cos",
  "tan",
  "floor",
  "ceil",
  "round",
] as const;

export type FormulaFunctionName = (typeof FORMULA_FUNCTIONS)[number];

export type FormulaNode =
  | { type: "number"; value: number }
  | { type: "param"; name: string }
  | { type: "binary"; op: "+" | "-" | "*" | "/" | "**" | "%"; left: FormulaNode; right: FormulaNode }
  | { type: "unary"; op: "+" | "-"; operand: FormulaNode }
  | { type: "call"; name: string; args: FormulaNode[] };

export class FormulaParseError extends Error {}

// ponytail: fixed cap, not configurable -- ask backend agent to reconcile if
// their Python validator lands on a different number. 20 comfortably covers
// any formula a slider-driven interactive would legitimately need, while
// keeping recursive-descent parsing well clear of a stack overflow.
const MAX_AST_DEPTH = 20;
const MAX_FORMULA_LENGTH = 500;

type TokenType = "number" | "identifier" | "operator" | "lparen" | "rparen" | "comma";

interface Token {
  type: TokenType;
  value: string;
}

const SINGLE_CHAR_OPERATORS = "+-*/%";

function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < source.length) {
    const ch = source[i];

    if (/\s/.test(ch)) {
      i++;
      continue;
    }

    if (/[0-9]/.test(ch)) {
      let j = i;
      let sawDot = false;
      while (j < source.length && (/[0-9]/.test(source[j]) || (source[j] === "." && !sawDot))) {
        if (source[j] === ".") sawDot = true;
        j++;
      }
      tokens.push({ type: "number", value: source.slice(i, j) });
      i = j;
      continue;
    }

    if (/[A-Za-z_]/.test(ch)) {
      let j = i + 1;
      while (j < source.length && /[A-Za-z0-9_]/.test(source[j])) j++;
      tokens.push({ type: "identifier", value: source.slice(i, j) });
      i = j;
      continue;
    }

    if (ch === "(") {
      tokens.push({ type: "lparen", value: ch });
      i++;
      continue;
    }
    if (ch === ")") {
      tokens.push({ type: "rparen", value: ch });
      i++;
      continue;
    }
    if (ch === ",") {
      tokens.push({ type: "comma", value: ch });
      i++;
      continue;
    }

    if (ch === "*" && source[i + 1] === "*") {
      tokens.push({ type: "operator", value: "**" });
      i += 2;
      continue;
    }
    if (SINGLE_CHAR_OPERATORS.includes(ch)) {
      tokens.push({ type: "operator", value: ch });
      i++;
      continue;
    }

    // Anything else -- `.` outside a numeric literal (member access), `[`/`]`
    // (computed access), `<`/`>`/`=`/`!` (comparisons), quotes (string
    // literals), `?`/`:` (ternaries), `=>` (arrow functions), backticks
    // (template literals) -- is rejected here, at the character level.
    throw new FormulaParseError(`Unexpected character "${ch}" at position ${i}`);
  }
  return tokens;
}

class Parser {
  private pos = 0;

  constructor(private readonly tokens: Token[]) {}

  parse(): FormulaNode {
    const node = this.parseExpression(0);
    if (this.pos < this.tokens.length) {
      throw new FormulaParseError(`Unexpected token "${this.tokens[this.pos].value}"`);
    }
    return node;
  }

  private checkDepth(depth: number): void {
    if (depth > MAX_AST_DEPTH) {
      throw new FormulaParseError(`Formula nesting exceeds max depth of ${MAX_AST_DEPTH}`);
    }
  }

  private peek(): Token | undefined {
    return this.tokens[this.pos];
  }

  private consume(): Token {
    const token = this.tokens[this.pos];
    if (!token) throw new FormulaParseError("Unexpected end of formula");
    this.pos++;
    return token;
  }

  // expression := term (('+' | '-') term)*
  //
  // NOTE on `depth`: it only increases at the four grammar points where a
  // formula string can force unbounded parser recursion -- parenthesized
  // groups, call arguments, chained unary signs, and right-associative `**`
  // chains. Walking through the ordinary precedence cascade
  // (expression -> term -> unary -> power -> primary) for a single,
  // non-nested operand passes `depth` through unchanged: a flat operator
  // chain like `2**2**2**2**2**2**2**2**2**2` should evaluate fine, while
  // `((((((...))))))` should be rejected well before it risks a real stack
  // overflow.
  private parseExpression(depth: number): FormulaNode {
    this.checkDepth(depth);
    let left = this.parseTerm(depth);
    while (this.peek()?.type === "operator" && (this.peek()?.value === "+" || this.peek()?.value === "-")) {
      const op = this.consume().value as "+" | "-";
      const right = this.parseTerm(depth);
      left = { type: "binary", op, left, right };
    }
    return left;
  }

  // term := unary (('*' | '/' | '%') unary)*
  private parseTerm(depth: number): FormulaNode {
    this.checkDepth(depth);
    let left = this.parseUnary(depth);
    while (this.peek()?.type === "operator" && ["*", "/", "%"].includes(this.peek()?.value ?? "")) {
      const op = this.consume().value as "*" | "/" | "%";
      const right = this.parseUnary(depth);
      left = { type: "binary", op, left, right };
    }
    return left;
  }

  // unary := ('-' | '+') unary | power
  private parseUnary(depth: number): FormulaNode {
    this.checkDepth(depth);
    const token = this.peek();
    if (token?.type === "operator" && (token.value === "-" || token.value === "+")) {
      this.consume();
      const operand = this.parseUnary(depth + 1); // nesting point: chained unary signs
      return { type: "unary", op: token.value as "+" | "-", operand };
    }
    return this.parsePower(depth);
  }

  // power := primary ('**' unary)?  -- right-associative, exponent may itself
  // be unary (so `2**-2` parses), matching the common `-2**2 === -(2**2)`
  // precedence convention.
  private parsePower(depth: number): FormulaNode {
    this.checkDepth(depth);
    const base = this.parsePrimary(depth);
    if (this.peek()?.type === "operator" && this.peek()?.value === "**") {
      this.consume();
      const exponent = this.parseUnary(depth + 1); // nesting point: right-associative ** chain
      return { type: "binary", op: "**", left: base, right: exponent };
    }
    return base;
  }

  // primary := number | identifier ['(' args ')'] | '(' expression ')'
  private parsePrimary(depth: number): FormulaNode {
    this.checkDepth(depth);
    const token = this.peek();
    if (!token) throw new FormulaParseError("Unexpected end of formula");

    if (token.type === "number") {
      this.consume();
      return { type: "number", value: Number(token.value) };
    }

    if (token.type === "lparen") {
      this.consume();
      const inner = this.parseExpression(depth + 1); // nesting point: parenthesized group
      if (this.peek()?.type !== "rparen") throw new FormulaParseError("Expected closing parenthesis");
      this.consume();
      return inner;
    }

    if (token.type === "identifier") {
      this.consume();
      if (this.peek()?.type === "lparen") {
        this.consume();
        const args: FormulaNode[] = [];
        if (this.peek()?.type !== "rparen") {
          args.push(this.parseExpression(depth + 1)); // nesting point: call argument
          while (this.peek()?.type === "comma") {
            this.consume();
            args.push(this.parseExpression(depth + 1));
          }
        }
        if (this.peek()?.type !== "rparen") throw new FormulaParseError("Expected closing parenthesis in call");
        this.consume();
        return { type: "call", name: token.value, args };
      }
      return { type: "param", name: token.value };
    }

    throw new FormulaParseError(`Unexpected token "${token.value}"`);
  }
}

function isWhitelistedFunction(name: string): name is FormulaFunctionName {
  return (FORMULA_FUNCTIONS as readonly string[]).includes(name);
}

/**
 * Default-deny validation pass over an already-parsed AST: every `param`
 * node's name must be in the caller's declared parameter set, every `call`
 * node's name must be in the function whitelist with the right arity, and
 * any node shape the parser could not have produced is rejected outright
 * (the `never` check below only compiles if every real case is handled).
 */
export function validateFormula(node: FormulaNode, paramNames: ReadonlySet<string>): void {
  switch (node.type) {
    case "number":
      return;
    case "param":
      if (!paramNames.has(node.name)) {
        throw new FormulaParseError(`Unknown parameter "${node.name}"`);
      }
      return;
    case "unary":
      validateFormula(node.operand, paramNames);
      return;
    case "binary":
      validateFormula(node.left, paramNames);
      validateFormula(node.right, paramNames);
      return;
    case "call": {
      if (!isWhitelistedFunction(node.name)) {
        throw new FormulaParseError(`Unknown function "${node.name}"`);
      }
      const variadic = node.name === "min" || node.name === "max";
      const validArity = variadic ? node.args.length >= 2 : node.args.length === 1;
      if (!validArity) {
        throw new FormulaParseError(
          variadic
            ? `"${node.name}" expects at least 2 arguments, got ${node.args.length}`
            : `"${node.name}" expects exactly 1 argument, got ${node.args.length}`,
        );
      }
      for (const arg of node.args) validateFormula(arg, paramNames);
      return;
    }
    default: {
      const exhaustiveCheck: never = node;
      throw new FormulaParseError(`Unsupported formula node: ${JSON.stringify(exhaustiveCheck)}`);
    }
  }
}

/**
 * Tokenizes, parses, and validates `source` against `paramNames`. This is
 * the only entry point callers should use -- it enforces the length cap
 * before tokenizing, the depth cap during parsing, and the whitelist/arity
 * checks before returning, so a returned AST is always safe to evaluate.
 */
export function parseFormula(source: string, paramNames: Iterable<string>): FormulaNode {
  if (source.length > MAX_FORMULA_LENGTH) {
    throw new FormulaParseError(`Formula exceeds max length of ${MAX_FORMULA_LENGTH} characters`);
  }
  const tokens = tokenize(source);
  if (tokens.length === 0) {
    throw new FormulaParseError("Formula is empty");
  }
  const ast = new Parser(tokens).parse();
  validateFormula(ast, new Set(paramNames));
  return ast;
}

// Security review LOW/MEDIUM: JS's Math.round rounds half-up
// (Math.round(0.5)===1) while Python's builtin round() uses banker's
// rounding (round(0.5)===0) -- for a product whose premise is exact
// traceability, a formula near a .5 boundary silently disagreeing between
// "validated on the backend" and "evaluated live here" is a real integrity
// concern, not a rendering nit. Neither builtin is used; both sides
// implement this same explicit rule instead (see formula.py's
// _round_half_away_from_zero).
function roundHalfAwayFromZero(x: number): number {
  return x >= 0 ? Math.floor(x + 0.5) : Math.ceil(x - 0.5);
}

// Matches Python's native `%` (sign follows the divisor) -- JS's native `%`
// follows the dividend instead (e.g. -1 % 3 is -1 in JS, 2 in Python).
function pythonStyleMod(a: number, b: number): number {
  return ((a % b) + b) % b;
}

function callFormulaFunction(name: FormulaFunctionName, args: number[]): number {
  // Only reachable from evaluateNode's "call" case below, on an AST that
  // validateFormula already confirmed uses a whitelisted name -- there is no
  // string-to-JS bridge here, each branch calls a fixed Math function.
  switch (name) {
    case "sqrt":
      return Math.sqrt(args[0]);
    case "abs":
      return Math.abs(args[0]);
    case "log":
      return Math.log(args[0]);
    case "exp":
      return Math.exp(args[0]);
    case "sin":
      return Math.sin(args[0]);
    case "cos":
      return Math.cos(args[0]);
    case "tan":
      return Math.tan(args[0]);
    case "floor":
      return Math.floor(args[0]);
    case "ceil":
      return Math.ceil(args[0]);
    case "round":
      return roundHalfAwayFromZero(args[0]);
    case "min":
      return Math.min(...args);
    case "max":
      return Math.max(...args);
  }
}

function applyBinaryOp(op: "+" | "-" | "*" | "/" | "**" | "%", left: number, right: number): number {
  switch (op) {
    case "+":
      return left + right;
    case "-":
      return left - right;
    case "*":
      return left * right;
    case "/":
      // Division by zero produces Infinity/-Infinity/NaN in JS, never
      // throws -- the UI renders that as "undefined".
      return left / right;
    case "%":
      return pythonStyleMod(left, right);
    case "**":
      return left ** right;
    default:
      return NaN; // unreachable -- every FormulaNode["binary"]["op"] is handled above
  }
}

function evaluateNode(node: FormulaNode, paramValues: Record<string, number>): number {
  switch (node.type) {
    case "number":
      return node.value;
    case "param": {
      const value = paramValues[node.name];
      return typeof value === "number" ? value : NaN;
    }
    case "unary": {
      const operand = evaluateNode(node.operand, paramValues);
      return node.op === "-" ? -operand : operand;
    }
    case "binary": {
      const left = evaluateNode(node.left, paramValues);
      const right = evaluateNode(node.right, paramValues);
      return applyBinaryOp(node.op, left, right);
    }
    case "call": {
      const args = node.args.map((arg) => evaluateNode(arg, paramValues));
      if (!isWhitelistedFunction(node.name)) return NaN; // unreachable on a validated AST
      return callFormulaFunction(node.name, args);
    }
    default:
      return NaN; // unreachable -- every FormulaNode variant is handled above
  }
}

/**
 * Walks an already-validated AST and computes its numeric result. Never
 * calls `eval`/`new Function`/`Function(...)` on the formula or any derived
 * string, at any point. Never throws -- an unexpected internal error
 * degrades to NaN (rendered as "undefined" by the UI) rather than crashing
 * the component a slider drag is wired to.
 */
export function evaluateFormula(node: FormulaNode, paramValues: Record<string, number>): number {
  try {
    return evaluateNode(node, paramValues);
  } catch {
    return NaN;
  }
}

/** True when `value` is safe to display as a normal number -- false for
 * NaN/Infinity/-Infinity, which the UI renders as "undefined" instead. */
export function isDefinedResult(value: number): boolean {
  return Number.isFinite(value);
}

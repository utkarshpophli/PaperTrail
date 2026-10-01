import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { DerivationList, InteractiveList, LearningPanel, QuizList } from "./learning-panel";
import { getLearning } from "@/lib/evidence-api";
import { ApiRequestError } from "@/lib/api-types";
import type {
  ClaimResponse,
  DerivationResponse,
  InteractiveResponse,
  LearningResponse,
  QuizQuestionResponse,
} from "@/lib/evidence-api";

vi.mock("@/lib/evidence-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/evidence-api")>("@/lib/evidence-api");
  return { ...actual, getLearning: vi.fn() };
});

const claim: ClaimResponse = {
  id: "claim-1",
  statement: "The model achieves 92% accuracy.",
  kind: "reported-result",
  verification_status: "verified",
  source_refs: [{ id: "ref-1", page: 4, excerpt: "we achieve 92% accuracy", locator: null }],
  created_at: "2024-01-01T00:00:00Z",
};

const question: QuizQuestionResponse = {
  id: "q1",
  order: 0,
  question: "What accuracy did the model achieve?",
  options: ["92%", "50%"],
  correct_answer: "92%",
  explanation: "The paper reports 92% accuracy on the benchmark.",
  claim_ids: ["claim-1"],
  created_at: "2024-01-01T00:00:00Z",
};

const derivation: DerivationResponse = {
  id: "d1",
  order: 0,
  title: "Loss derivation",
  steps: [{ explanation: "Start from the cross-entropy loss", formula: "L = -sum(y * log(p))", claim_ids: ["claim-1"] }],
  created_at: "2024-01-01T00:00:00Z",
};

const interactive: InteractiveResponse = {
  id: "i1",
  title: "Loss vs. learning rate",
  description: "See how the reported loss scales with learning rate.",
  parameters: [{ name: "lr", label: "Learning rate", min: 0, max: 10, step: 1, default: 2, unit: null }],
  formula: "lr * 2",
  output_label: "Loss",
  claim_ids: ["claim-1"],
  created_at: "2024-01-01T00:00:00Z",
};

describe("QuizList", () => {
  it("hides the answer until revealed", () => {
    render(<QuizList questions={[question]} claims={[claim]} />);

    expect(screen.getByText(question.question)).toBeInTheDocument();
    expect(screen.queryByText(question.explanation)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /reveal answer/i }));

    expect(screen.getByText(question.explanation)).toBeInTheDocument();
    expect(screen.getByText("Answer:")).toBeInTheDocument();
  });
});

describe("DerivationList", () => {
  it("renders each step's explanation and formula as plain text, with claim references", () => {
    render(<DerivationList derivations={[derivation]} claims={[claim]} />);

    expect(screen.getByText(derivation.title)).toBeInTheDocument();
    expect(screen.getByText("Start from the cross-entropy loss")).toBeInTheDocument();
    expect(screen.getByText("L = -sum(y * log(p))")).toBeInTheDocument();
    expect(screen.getByText(claim.statement)).toBeInTheDocument();
  });
});

describe("InteractiveList", () => {
  it("recomputes the displayed output when a slider changes", () => {
    render(<InteractiveList interactives={[interactive]} claims={[claim]} />);

    expect(screen.getByText("Loss vs. learning rate")).toBeInTheDocument();
    expect(screen.getByText("Loss:")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument(); // default lr=2 -> 2*2

    const slider = screen.getByLabelText("Learning rate") as HTMLInputElement;
    fireEvent.change(slider, { target: { value: "5" } });

    expect(screen.getByText("10")).toBeInTheDocument(); // lr=5 -> 5*2
    expect(screen.queryByText("4")).not.toBeInTheDocument();
  });

  it("renders 'undefined' instead of crashing when the formula divides by zero", () => {
    const divideByZero: InteractiveResponse = {
      ...interactive,
      id: "i2",
      formula: "1 / lr",
      parameters: [{ name: "lr", label: "Learning rate", min: 0, max: 10, step: 1, default: 0, unit: null }],
    };
    render(<InteractiveList interactives={[divideByZero]} claims={[claim]} />);

    expect(screen.getByText("undefined")).toBeInTheDocument();
  });
});

describe("LearningPanel", () => {
  it("shows a calm not-generated state on the matching 404 code", async () => {
    vi.mocked(getLearning).mockRejectedValueOnce(
      new ApiRequestError(404, { code: "learning_not_found", message: "Learning not found" }),
    );
    render(<LearningPanel paperId="paper-1" claims={[claim]} refreshKey={0} />);

    expect(await screen.findByText(/not generated yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders primer, application guide, quiz, and derivations once loaded", async () => {
    const learning: LearningResponse = {
      paper_id: "paper-1",
      primer: [{ id: "p1", title: "Intro", content: "Plain-language intro.", order: 0, claim_ids: ["claim-1"], created_at: "" }],
      application_guide: [
        { id: "a1", title: "Try it", content: "How to apply this.", order: 0, claim_ids: ["claim-1"], created_at: "" },
      ],
      quiz: [question],
      derivations: [derivation],
      interactives: [interactive],
    };
    vi.mocked(getLearning).mockResolvedValueOnce(learning);
    render(<LearningPanel paperId="paper-1" claims={[claim]} refreshKey={0} />);

    expect(await screen.findByText("Intro")).toBeInTheDocument();
    expect(screen.getByText("Try it")).toBeInTheDocument();
    expect(screen.getByText(question.question)).toBeInTheDocument();
    expect(screen.getByText(derivation.title)).toBeInTheDocument();
  });
});

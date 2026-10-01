"""Content for the demo paper seeded by ``scripts.seed_demo``.

EVERYTHING HERE IS FABRICATED. "LatticeNet" is not a real model and none of the
numbers below are real results; the page text, thesis and summary all say so.
Excerpts are verbatim substrings of ``PAGES`` (checked at import), so the
quote-exactness verifier really would confirm them.
"""

import uuid

from app.evidence.schemas import (
    ClaimExtraction,
    DerivationDraft,
    DerivationStepDraft,
    ExtractionResult,
    GeneratedSectionDraft,
    GlossaryTermExtraction,
    InteractiveDraft,
    InteractiveParameterDraft,
    MetricExtraction,
    NarrativeExtraction,
    QuizQuestionDraft,
    SourceRefExtraction,
)
from app.evidence.story_visuals import StorySpec
from app.models.claim import ClaimKind

TITLE = "Demo paper (illustrative data)"
ILLUSTRATIVE_NOTE = "This is fabricated demonstration content, not a real paper; none of its numbers are real results."

PAGES: dict[int, str] = {
    1: (
        "DEMO PAPER (ILLUSTRATIVE DATA). This text is fabricated demonstration content for Paper Trail. "
        "It is not a real paper, and none of its numbers are real results.\n\n"
        "Abstract. We describe LatticeNet, a fictional sparse routing network. LatticeNet routes each token to a "
        "small subset of expert blocks, which reduces compute per token. On an illustrative benchmark LatticeNet "
        "reaches 84.2 accuracy versus 79.5 for the dense baseline.\n\n"
        "1 Introduction. Dense models spend the same compute on every token. We ask whether routing tokens to a few "
        "experts can keep accuracy while lowering cost.\n\n"
        "Figure 1: Overall architecture of LatticeNet (illustrative diagram)."
    ),
    2: (
        "2 Method. LatticeNet has three parts: a token encoder, a router, and a pool of expert blocks. The router "
        "scores every expert for each token and keeps the top two. Training minimizes L = L_task + lambda * "
        "L_balance, where L_balance penalizes uneven expert load.\n\n"
        "Figure 2: Accuracy by model on the illustrative benchmark."
    ),
    3: (
        "3 Results. LatticeNet reaches 84.2 accuracy versus 79.5 for the dense baseline and 81.0 for a "
        "static-pruning baseline. Compute per token is 0.6x of the dense baseline.\n\n"
        "Figure 3: How tokens are routed to experts (illustrative schematic).\n\n"
        "4 Limitations. Routing becomes unstable when fewer than two experts are active. The illustrative "
        "benchmark covers a single task.\n\n"
        "5 Conclusion. Sparse routing is a promising way to trade compute for accuracy in this fictional setting."
    ),
}

FIGURES: list[dict[str, object]] = [
    {"page": 1, "caption": "Figure 1: Overall architecture of LatticeNet (illustrative diagram).", "image_path": "figures/page1_fig0.png"},
    {"page": 2, "caption": "Figure 2: Accuracy by model on the illustrative benchmark.", "image_path": "figures/page2_fig0.png"},
    {"page": 3, "caption": "Figure 3: How tokens are routed to experts (illustrative schematic).", "image_path": "figures/page3_fig0.png"},
]

# key -> (statement, kind, [(page, excerpt)]). Keys are how the story/report/etc. below cite claims.
_CLAIMS: dict[str, tuple[str, ClaimKind, list[tuple[int, str]]]] = {
    "route": (
        "LatticeNet routes each token to a small subset of expert blocks.",
        ClaimKind.method,
        [(1, "LatticeNet routes each token to a small subset of expert blocks, which reduces compute per token")],
    ),
    "top2": (
        "The router scores every expert for each token and keeps the top two.",
        ClaimKind.method,
        [(2, "The router scores every expert for each token and keeps the top two")],
    ),
    "loss": (
        "Training balances expert load with an auxiliary loss term.",
        ClaimKind.method,
        [(2, "Training minimizes L = L_task + lambda * L_balance, where L_balance penalizes uneven expert load")],
    ),
    "accuracy": (
        "LatticeNet reaches 84.2 accuracy versus 79.5 for the dense baseline.",
        ClaimKind.reported_result,
        [(3, "LatticeNet reaches 84.2 accuracy versus 79.5 for the dense baseline")],
    ),
    "compute": (
        "Compute per token is 0.6x of the dense baseline.",
        ClaimKind.reported_result,
        [(3, "Compute per token is 0.6x of the dense baseline")],
    ),
    "dense": (
        "Dense models spend the same compute on every token.",
        ClaimKind.background,
        [(1, "Dense models spend the same compute on every token")],
    ),
    # Two words swapped: the verifier classifies this as partially-matched.
    "tradeoff": (
        "Sparse routing trades compute for accuracy.",
        ClaimKind.author_interpretation,
        [(3, "Sparse routing is a way promising to trade compute for accuracy")],
    ),
    "unstable": (
        "Routing becomes unstable when fewer than two experts are active.",
        ClaimKind.limitation,
        [(3, "Routing becomes unstable when fewer than two experts are active")],
    ),
    # Cites a page that does not exist: the verifier cannot check it, so needs-review.
    "single_task": (
        "The benchmark covers a single task.",
        ClaimKind.limitation,
        [(4, "The illustrative benchmark covers a single task")],
    ),
    # A changed digit: the verifier classifies this as a mismatch (kept to show that state, never used downstream).
    "wrong_number": (
        "LatticeNet reaches 84.9 accuracy versus the dense baseline.",
        ClaimKind.reported_result,
        [(3, "LatticeNet reaches 84.9 accuracy versus 79.5 for the dense baseline")],
    ),
}
CLAIM_KEYS = list(_CLAIMS)

_METRICS = [
    ("LatticeNet accuracy", "84.2", "84.2", "accuracy", 3, "LatticeNet reaches 84.2 accuracy"),
    ("Dense baseline accuracy", "79.5", "79.5", "accuracy", 3, "79.5 for the dense baseline"),
    ("Static-pruning baseline accuracy", "81.0", "81.0", "accuracy", 3, "81.0 for a static-pruning baseline"),
    ("Compute per token vs dense", "0.6", "0.6x", None, 3, "Compute per token is 0.6x of the dense baseline"),
]

_GENERAL = "General term (not defined in this paper): "
_GLOSSARY = [
    ("Router", "The component that scores experts for each token and picks which ones run.", 2, "The router scores every expert for each token"),
    ("Expert block", "One of the parallel sub-networks a token can be routed to.", 1, "a small subset of expert blocks"),
    ("Load-balancing loss", "A penalty that discourages sending most tokens to the same few experts.", 2, "L_balance penalizes uneven expert load"),
    ("Dense baseline", "A model in which every token uses all of the model's compute.", 3, "the dense baseline"),
    ("Top-k routing", _GENERAL + "Keeping only the k highest-scoring options.", None, None),
]


def _check_excerpts() -> None:
    for key, (_, _, refs) in _CLAIMS.items():
        for page, excerpt in refs:
            if key in {"tradeoff", "single_task", "wrong_number"}:
                continue  # deliberately imperfect, to show non-verified states
            assert excerpt in PAGES[page], f"claim {key}: excerpt not on page {page}"
    for *_, page, excerpt in _METRICS:
        assert excerpt in PAGES[page]
    for _, _, page, excerpt in _GLOSSARY:
        assert page is None or (excerpt or "") in PAGES[page]


_check_excerpts()


def extraction_result() -> ExtractionResult:
    return ExtractionResult(
        claims=[
            ClaimExtraction(
                statement=statement,
                kind=kind,
                source_refs=[SourceRefExtraction(page=page, excerpt=excerpt) for page, excerpt in refs],
            )
            for statement, kind, refs in _CLAIMS.values()
        ],
        metrics=[
            MetricExtraction(
                label=label, value=value, display_value=display, unit=unit, source_page=page, source_excerpt=excerpt
            )
            for label, value, display, unit, page, excerpt in _METRICS
        ],
        glossary=[
            GlossaryTermExtraction(term=term, definition=definition, source_page=page, source_excerpt=excerpt)
            for term, definition, page, excerpt in _GLOSSARY
        ],
        narrative=NarrativeExtraction(
            thesis=f"Illustrative demo: a fictional sparse routing network, LatticeNet, keeps accuracy while using less compute. {ILLUSTRATIVE_NOTE}",
            plain_summary=(
                "LatticeNet is an invented model used to demonstrate Paper Trail. It sends each token to only a few "
                f"expert blocks instead of the whole network. {ILLUSTRATIVE_NOTE}"
            ),
            research_question="Illustrative: can routing tokens to a few experts keep accuracy while lowering cost?",
        ),
    )


def _draft(heading: str, body: str, *keys: str, ids: dict[str, uuid.UUID]) -> GeneratedSectionDraft:
    return GeneratedSectionDraft(heading=heading, body=body, claim_ids=[ids[k] for k in keys])


def report_drafts(ids: dict[str, uuid.UUID]) -> list[GeneratedSectionDraft]:
    return [
        _draft("Overview", f"The demo paper introduces LatticeNet, a fictional sparse routing network. {ILLUSTRATIVE_NOTE}", "route", "dense", ids=ids),
        _draft("Method", "Each token is scored against every expert by a router; only the top two experts run. A balance term keeps the load even.", "route", "top2", "loss", ids=ids),
        _draft("Results and limits", "On the illustrative benchmark LatticeNet reaches 84.2 accuracy against 79.5 for the dense baseline at 0.6x the compute, but routing becomes unstable with fewer than two active experts.", "accuracy", "compute", "unstable", ids=ids),
    ]


def technical_drafts(ids: dict[str, uuid.UUID]) -> list[GeneratedSectionDraft]:
    return [
        _draft("Router", "The router produces one score per expert per token and keeps the two highest.", "top2", ids=ids),
        _draft("Training objective", "The objective is L = L_task + lambda * L_balance, where the second term penalizes uneven expert load.", "loss", ids=ids),
        _draft("Reported metrics", "Accuracy: 84.2 (LatticeNet) versus 79.5 (dense) and 81.0 (static pruning). Compute per token: 0.6x of dense.", "accuracy", "compute", ids=ids),
    ]


def primer_drafts(ids: dict[str, uuid.UUID]) -> list[GeneratedSectionDraft]:
    return [
        _draft("Dense versus sparse models", "A dense model uses all of its parameters for every token. A sparse model sends each token to only some of them.", "dense", "route", ids=ids),
        _draft("What is a router?", "A router is a small component that scores the available experts and decides which ones a token visits.", "top2", ids=ids),
    ]


def application_guide_drafts(ids: dict[str, uuid.UUID]) -> list[GeneratedSectionDraft]:
    return [
        _draft("When this idea applies", "Consider sparse routing when compute per token matters and you can tolerate added routing complexity. This paper is illustrative only.", "compute", "tradeoff", ids=ids),
        _draft("What to watch for", "The demo paper reports instability with fewer than two active experts, so keep at least two.", "unstable", ids=ids),
    ]


def quiz_drafts(ids: dict[str, uuid.UUID]) -> list[QuizQuestionDraft]:
    return [
        QuizQuestionDraft(
            question="How many experts does the router keep for each token?",
            options=["One", "Two", "All of them"],
            correct_answer="Two",
            explanation="The router scores every expert and keeps the top two.",
            claim_ids=[ids["top2"]],
        ),
        QuizQuestionDraft(
            question="What does the balance term in the training loss penalize?",
            options=None,
            correct_answer="Uneven expert load",
            explanation="L_balance penalizes uneven expert load.",
            claim_ids=[ids["loss"]],
        ),
        QuizQuestionDraft(
            question="Which baseline scores lowest on the illustrative benchmark?",
            options=["Dense baseline", "Static-pruning baseline", "LatticeNet"],
            correct_answer="Dense baseline",
            explanation="Dense scores 79.5, static pruning 81.0, LatticeNet 84.2 (illustrative numbers).",
            claim_ids=[ids["accuracy"]],
        ),
    ]


def derivation_drafts(ids: dict[str, uuid.UUID]) -> list[DerivationDraft]:
    return [
        DerivationDraft(
            title="Building the training objective",
            steps=[
                DerivationStepDraft(explanation="Start from the task loss.", formula="L = L_task", claim_ids=[ids["loss"]]),
                DerivationStepDraft(
                    explanation="Add a penalty on uneven expert load, weighted by lambda.",
                    formula="L = L_task + lambda * L_balance",
                    claim_ids=[ids["loss"]],
                ),
            ],
        )
    ]


def interactive_drafts(ids: dict[str, uuid.UUID]) -> list[InteractiveDraft]:
    return [
        InteractiveDraft(
            title="Fraction of experts active (illustrative)",
            description="Illustrative playground: the slider values are teaching values, not results from the paper.",
            parameters=[
                InteractiveParameterDraft(name="total_experts", label="Total experts (illustrative)", min=2, max=16, step=1, default=8),
                InteractiveParameterDraft(name="active_experts", label="Active experts per token", min=1, max=8, step=1, default=2),
            ],
            formula="active_experts / total_experts",
            output_label="Fraction of experts active (illustrative)",
            claim_ids=[ids["top2"]],
        )
    ]


def figure_links(ids: dict[str, uuid.UUID]) -> dict[str, tuple[list[uuid.UUID], str]]:
    return {
        "page1_fig0.png": ([ids["route"], ids["top2"]], "Shows the encoder, router and expert pool that the method claims describe, in one picture."),
        "page2_fig0.png": ([ids["accuracy"]], "Puts the three accuracy numbers side by side so the gap to the dense baseline is visible."),
        "page3_fig0.png": ([ids["top2"], ids["unstable"]], "Shows the routing step where the top-two choice happens, and where instability arises with too few experts."),
    }


def story(ids: dict[str, uuid.UUID]) -> StorySpec:
    def sec(kicker: str, title: str, body: str, keys: list[str], visual: dict) -> dict:
        return {"kicker": kicker, "title": title, "body": body, "claim_ids": [str(ids[k]) for k in keys], "visual": visual}

    quote = "LatticeNet routes each token to a small subset of expert blocks, which reduces compute per token"
    sections = [
        sec("The problem", "Every token costs the same", "In a dense model every token gets the full compute budget, however easy it is. That is the cost this demo paper sets out to cut.", ["dense"], {
            "type": "concept", "eyebrow": "Concept", "caption": "The dense-model cost the paper wants to reduce.", "center": "Dense compute",
            "items": [{"label": "Every token", "detail": "Each token passes through the whole network."}, {"label": "Same compute", "detail": "Easy and hard tokens cost the same."}, {"label": "Room to save", "detail": "The paper asks whether that is necessary."}]}),
        sec("The idea", "Send tokens only where they matter", "LatticeNet encodes a token, lets a router score the experts, keeps the top two, and combines their outputs.", ["route", "top2"], {
            "type": "flow", "eyebrow": "How it works", "caption": "The path one token takes through LatticeNet.",
            "items": [{"label": "Encode", "detail": "The token encoder embeds the token."}, {"label": "Score", "detail": "The router scores every expert."}, {"label": "Keep top two", "detail": "Only the two best experts run."}, {"label": "Combine", "detail": "Their outputs are merged."}]}),
        sec("The design", "Three parts, one path", "A token encoder, a router and a pool of expert blocks make up the model.", ["route"], {
            "type": "architecture", "eyebrow": "Architecture", "caption": "The three parts named in the method section.",
            "nodes": [
                {"id": "tokens", "label": "Tokens", "detail": "The input sequence.", "group": "input"},
                {"id": "encoder", "label": "Token encoder", "detail": "Embeds each token.", "group": "core"},
                {"id": "router", "label": "Router", "detail": "Scores experts, keeps the top two.", "group": "core"},
                {"id": "experts", "label": "Expert blocks", "detail": "Parallel sub-networks.", "group": "core"},
                {"id": "out", "label": "Output", "detail": "Combined result.", "group": "output"},
                {"id": "claim", "label": "Method claims", "detail": "Where the paper states this design.", "group": "evidence"}],
            "edges": [{"source": "tokens", "target": "encoder", "label": ""}, {"source": "encoder", "target": "router", "label": "embedding"}, {"source": "router", "target": "experts", "label": "top two"}, {"source": "experts", "target": "out", "label": ""}, {"source": "claim", "target": "router", "label": "describes"}]}),
        sec("The objective", "Keeping the load even", "Training adds a balance penalty to the task loss so tokens do not all pile onto the same experts.", ["loss"], {
            "type": "equation", "eyebrow": "Equation", "caption": "The training objective as written in the method section.", "formula": "L = L_task + lambda * L_balance",
            "terms": [{"symbol": "L_task", "label": "Task loss", "detail": "How well the model does its job."}, {"symbol": "L_balance", "label": "Balance loss", "detail": "Penalizes uneven expert load."}, {"symbol": "lambda", "label": "Weight", "detail": "How strongly balance is enforced."}],
            "steps": ["Start from the task loss.", "Add the balance penalty, weighted by lambda."]}),
        sec("The result", "Better accuracy, less compute", "On the illustrative benchmark LatticeNet reaches 84.2 accuracy, and it uses 0.6x the compute per token.", ["accuracy", "compute"], {
            "type": "metric", "eyebrow": "Key numbers", "caption": "Headline numbers from the results section (illustrative).",
            "items": [{"label": "LatticeNet accuracy", "value": "84.2", "note": "Illustrative benchmark"}, {"label": "Dense baseline accuracy", "value": "79.5", "note": "Illustrative benchmark"}, {"label": "Compute per token", "value": "0.6x", "note": "Relative to dense"}]}),
        sec("Head to head", "Three models, one benchmark", "LatticeNet leads both baselines on the illustrative benchmark.", ["accuracy"], {
            "type": "comparison", "eyebrow": "Comparison", "caption": "Accuracy on the illustrative benchmark.",
            "items": [{"label": "LatticeNet", "value": 84.2, "display_value": "84.2", "highlight": True}, {"label": "Static pruning", "value": 81.0, "display_value": "81.0", "highlight": False}, {"label": "Dense baseline", "value": 79.5, "display_value": "79.5", "highlight": False}]}),
        sec("In their words", "The core claim", "The abstract states the idea in one sentence.", ["route"], {
            "type": "quote", "eyebrow": "From the paper", "caption": "Verbatim from page 1.", "quote": quote, "attribution": "Demo paper (illustrative data), abstract"}),
        sec("The stack", "Three layers of the model", "Read from the bottom up, the model is an encoder, a router, and experts.", ["route", "top2"], {
            "type": "layers", "eyebrow": "Layers", "caption": "The three parts, bottom to top.",
            "items": [{"label": "Token encoder", "detail": "Embeds the input.", "tone": "paper"}, {"label": "Router", "detail": "Chooses the experts.", "tone": "accent"}, {"label": "Expert blocks", "detail": "Do the heavy compute.", "tone": "ink"}]}),
        sec("The routine", "What happens for each token", "For every token the same four steps repeat.", ["top2", "loss"], {
            "type": "timeline", "eyebrow": "Sequence", "caption": "The order of operations for one token during training.",
            "items": [{"label": "Encode", "detail": "Embed the token.", "tone": "paper"}, {"label": "Score", "detail": "Rate every expert.", "tone": "accent"}, {"label": "Keep two", "detail": "Run only the top two.", "tone": "accent"}, {"label": "Balance", "detail": "Penalize uneven load.", "tone": "ink"}]}),
        sec("The trade-off", "What you gain and give up", "Accuracy goes up and compute goes down; the paper does not report other costs.", ["accuracy", "compute", "tradeoff"], {
            "type": "matrix", "eyebrow": "Trade-offs", "caption": "Qualitative summary of the reported numbers (illustrative).",
            "columns": ["Dense", "Static pruning", "LatticeNet"],
            "rows": [
                {"label": "Accuracy", "cells": [{"label": "79.5", "tone": "low"}, {"label": "81.0", "tone": "medium"}, {"label": "84.2", "tone": "high"}]},
                {"label": "Compute per token", "cells": [{"label": "Full", "tone": "high"}, {"label": "Not reported", "tone": "neutral"}, {"label": "0.6x", "tone": "low"}]}]}),
        sec("The catch", "Where it breaks", "Routing becomes unstable when fewer than two experts are active, and the benchmark covers a single task.", ["unstable", "single_task"], {
            "type": "infographic", "eyebrow": "Limitations", "caption": "The limits the paper states.",
            "items": [{"label": "Too few experts", "detail": "Routing becomes unstable below two active experts.", "badge": "Limitation"}, {"label": "One task", "detail": "The illustrative benchmark covers a single task.", "badge": "Limitation"}, {"label": "Illustrative only", "detail": "None of this is a real result.", "badge": "Demo"}]}),
    ]
    return StorySpec.model_validate(
        {
            "meta": {
                "title": "Demo paper (illustrative data): LatticeNet in pictures",
                "dek": "A fabricated walkthrough that shows every visual type. Not a real paper.",
                "reading_time": "4 min read",
                "closing": {"title": "What to take away", "body": f"Sparse routing trades compute for accuracy in this fictional setting. {ILLUSTRATIVE_NOTE}"},
            },
            "sections": sections,
        }
    )

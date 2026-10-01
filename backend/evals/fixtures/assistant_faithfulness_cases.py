"""Hand-written cases for the Research Assistant answer-faithfulness eval
(``run_assistant_faithfulness_eval.py``).

Each case supplies a known, closed claim set (mirroring what
``app.evidence.service.run_assistant`` would load from the DB for a real
paper) plus a question/action. The eval doesn't need a separate "ground
truth answer" -- what it measures is whether the assistant's cited
``claim_ids`` are ones that were actually offered to it as context (see
``run_assistant_faithfulness_eval.py``'s docstring for exactly how that's
measured against the real ``app.evidence.assistant`` code path).

Claim excerpts here are verbatim substrings of each fixture paper's text
(``evals/fixtures/hallucination_fixtures/papers.py``) -- real, verifiable
quotes, not invented ones, since a faithfulness eval built on fabricated
"ground truth" claims would be measuring nothing real.
"""

import uuid
from dataclasses import dataclass, field

from app.evidence.schemas import (
    AssistantClaimForPrompt,
    GlossaryTermForPrompt,
    MetricForPrompt,
)
from app.models.claim import ClaimKind, VerificationStatus

_NAMESPACE = uuid.UUID("6f6e1e2a-7f1e-4f5a-9b7c-9a1a9a1a9a1a")


def _claim_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, name)


@dataclass(frozen=True)
class AssistantFaithfulnessCase:
    id: str
    action: str
    question: str | None
    thesis: str
    plain_summary: str
    research_question: str
    claims: list[AssistantClaimForPrompt]
    metrics: list[MetricForPrompt] = field(default_factory=list)
    glossary: list[GlossaryTermForPrompt] = field(default_factory=list)


_VISION_CLAIMS = [
    AssistantClaimForPrompt(
        id=_claim_id("vision_result"),
        kind=ClaimKind.reported_result,
        statement="SparseGrid-Net reaches 79.4% top-1 accuracy on CIFAR-100 with 38% fewer FLOPs than ResNet-50.",
        excerpts=[
            "SparseGrid-Net reaches 79.4% top-1 accuracy while using 38% fewer floating point "
            "operations than a ResNet-50 baseline trained under identical settings."
        ],
        verification_status=VerificationStatus.verified,
    ),
    AssistantClaimForPrompt(
        id=_claim_id("vision_method"),
        kind=ClaimKind.method,
        statement="Training used AdamW, learning rate 3e-4, batch size 256, 200 epochs on four A100 GPUs.",
        excerpts=[
            "Training used the AdamW optimizer with a learning rate of 3e-4 and a batch size of "
            "256, for 200 epochs on four A100 GPUs."
        ],
        verification_status=VerificationStatus.verified,
    ),
    AssistantClaimForPrompt(
        id=_claim_id("vision_limitation"),
        kind=ClaimKind.limitation,
        statement="SparseGrid-Net's routing pattern is fixed at initialization and does not adapt during training.",
        excerpts=[
            "A key limitation is that SparseGrid-Net's routing pattern is fixed at initialization "
            "and does not adapt during training"
        ],
        verification_status=VerificationStatus.verified,
    ),
    AssistantClaimForPrompt(
        id=_claim_id("vision_no_imagenet"),
        kind=ClaimKind.limitation,
        statement="SparseGrid-Net was not evaluated on ImageNet due to compute constraints.",
        excerpts=[
            "We did not evaluate SparseGrid-Net on ImageNet due to compute constraints."
        ],
        verification_status=VerificationStatus.verified,
    ),
]

_NLP_CLAIMS = [
    AssistantClaimForPrompt(
        id=_claim_id("nlp_result"),
        kind=ClaimKind.reported_result,
        statement="ClauseLink improves F1 from 71.2 to 76.8 on ContractCoref over the previous best system.",
        excerpts=[
            "ClauseLink improves F1 from 71.2 to 76.8 over the previous best system."
        ],
        verification_status=VerificationStatus.verified,
    ),
    AssistantClaimForPrompt(
        id=_claim_id("nlp_finding"),
        kind=ClaimKind.reported_result,
        statement="Most of ClauseLink's gain comes from documents longer than 2,000 tokens.",
        excerpts=[
            "A key finding is that most of ClauseLink's gain comes from documents longer than "
            "2,000 tokens, where clause-boundary information is most informative"
        ],
        verification_status=VerificationStatus.verified,
    ),
    AssistantClaimForPrompt(
        id=_claim_id("nlp_limitation"),
        kind=ClaimKind.limitation,
        statement="ClauseLink was evaluated only on English-language contracts.",
        excerpts=[
            "ClauseLink was evaluated only on English-language contracts and its performance on other languages is untested."
        ],
        verification_status=VerificationStatus.verified,
    ),
]

_RL_CLAIMS = [
    AssistantClaimForPrompt(
        id=_claim_id("rl_result"),
        kind=ClaimKind.reported_result,
        statement="CautiousExplore reduces unsafe episode terminations by 62% versus a PPO baseline.",
        excerpts=[
            "CautiousExplore reduces the number of unsafe episode terminations by 62% relative to "
            "a proximal policy optimization baseline"
        ],
        verification_status=VerificationStatus.verified,
    ),
    AssistantClaimForPrompt(
        id=_claim_id("rl_cost"),
        kind=ClaimKind.reported_result,
        statement="CautiousExplore converges 9% slower than the PPO baseline to the same final reward.",
        excerpts=["at the cost of a 9% slower convergence to the same final reward"],
        verification_status=VerificationStatus.verified,
    ),
    AssistantClaimForPrompt(
        id=_claim_id("rl_limitation"),
        kind=ClaimKind.limitation,
        statement="CautiousExplore is not tested in a multi-agent setting.",
        excerpts=["The paper does not test CautiousExplore in a multi-agent setting."],
        verification_status=VerificationStatus.verified,
    ),
]


CASES: list[AssistantFaithfulnessCase] = [
    AssistantFaithfulnessCase(
        id="vision_understand",
        action="understand",
        question=None,
        thesis="A learned sparse routing pattern can replace dense convolutions with less compute.",
        plain_summary="SparseGrid-Net classifies images with fewer operations than ResNet-50.",
        research_question="Can a fixed sparse routing pattern match dense-convolution accuracy at lower cost?",
        claims=_VISION_CLAIMS,
    ),
    AssistantFaithfulnessCase(
        id="nlp_deep_dive",
        action="deep-dive",
        question="How much does ClauseLink improve F1 over the previous best system, and on what kind of documents?",
        thesis="Modeling clause boundaries as graph edges improves coreference resolution in long legal text.",
        plain_summary="ClauseLink links related clauses in contracts to resolve references more accurately.",
        research_question="Does explicit clause-boundary modeling help coreference resolution in legal documents?",
        claims=_NLP_CLAIMS,
    ),
    AssistantFaithfulnessCase(
        id="rl_verify",
        action="verify",
        question="Does the paper claim CautiousExplore was tested in a multi-agent setting?",
        thesis="Estimating epistemic uncertainty over action-values can reduce unsafe exploration.",
        plain_summary="CautiousExplore avoids risky actions early in training by tracking its own uncertainty.",
        research_question="Can uncertainty-aware exploration reduce unsafe actions without much reward cost?",
        claims=_RL_CLAIMS,
    ),
    AssistantFaithfulnessCase(
        id="vision_challenge",
        action="challenge",
        question=None,
        thesis="A learned sparse routing pattern can replace dense convolutions with less compute.",
        plain_summary="SparseGrid-Net classifies images with fewer operations than ResNet-50.",
        research_question="Can a fixed sparse routing pattern match dense-convolution accuracy at lower cost?",
        claims=_VISION_CLAIMS,
    ),
]

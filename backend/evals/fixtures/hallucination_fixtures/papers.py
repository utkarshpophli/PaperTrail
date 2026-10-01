"""Synthetic "papers" for the hallucination-rate eval.

These are fabricated abstract+body text, NOT real papers -- they exist only
to give the real extraction prompts (``app.evidence.extraction``) something
concrete to extract claims/metrics from, with text short enough to keep the
eval cheap to run against a real provider. Ground truth is the text itself:
a claim/metric extracted from one of these fixtures either verifies against
this same page text (via ``app.evidence.verifier.verify_claim_status``) or
it doesn't -- there's no separate "answer key" to maintain in parallel.

Each fixture deliberately contains numbers/statements that DON'T appear
together elsewhere, precisely so a provider that pattern-completes a
plausible-sounding but unsupported number produces a real, catchable
hallucination rather than an accidental true positive.
"""

from dataclasses import dataclass

from app.evidence.schemas import PageText


@dataclass(frozen=True)
class HallucinationFixture:
    name: str
    pages: list[PageText]


FIXTURES: list[HallucinationFixture] = [
    HallucinationFixture(
        name="synthetic_vision_paper",
        pages=[
            PageText(
                number=1,
                text=(
                    "We propose SparseGrid-Net, a convolutional architecture for image "
                    "classification that replaces dense 3x3 convolutions with a learned "
                    "sparse routing pattern. On the CIFAR-100 benchmark, SparseGrid-Net "
                    "reaches 79.4% top-1 accuracy while using 38% fewer floating point "
                    "operations than a ResNet-50 baseline trained under identical settings. "
                    "Training used the AdamW optimizer with a learning rate of 3e-4 and a "
                    "batch size of 256, for 200 epochs on four A100 GPUs. A key limitation "
                    "is that SparseGrid-Net's routing pattern is fixed at initialization and "
                    "does not adapt during training, which the authors note may limit "
                    "performance on datasets with highly non-uniform class distributions. "
                    "We did not evaluate SparseGrid-Net on ImageNet due to compute constraints."
                ),
            )
        ],
    ),
    HallucinationFixture(
        name="synthetic_nlp_paper",
        pages=[
            PageText(
                number=1,
                text=(
                    "This paper introduces ClauseLink, a method for improving coreference "
                    "resolution in long legal documents by explicitly modeling clause "
                    "boundaries as graph edges. On the ContractCoref benchmark, ClauseLink "
                    "improves F1 from 71.2 to 76.8 over the previous best system. The model "
                    "has 110 million parameters and is initialized from a pretrained "
                    "RoBERTa-base encoder. A key finding is that most of ClauseLink's gain "
                    "comes from documents longer than 2,000 tokens, where clause-boundary "
                    "information is most informative; on shorter documents the improvement "
                    "over the baseline is not statistically significant. The authors note "
                    "that ClauseLink was evaluated only on English-language contracts and "
                    "its performance on other languages is untested."
                ),
            )
        ],
    ),
    HallucinationFixture(
        name="synthetic_rl_paper",
        pages=[
            PageText(
                number=1,
                text=(
                    "We present CautiousExplore, a reinforcement learning agent that "
                    "estimates epistemic uncertainty over its own action-value function to "
                    "avoid catastrophic actions during early training. Across six control "
                    "tasks from a standard continuous-control suite, CautiousExplore reduces "
                    "the number of unsafe episode terminations by 62% relative to a "
                    "proximal policy optimization baseline, at the cost of a 9% slower "
                    "convergence to the same final reward. All experiments used three random "
                    "seeds. The authors report that CautiousExplore's uncertainty estimate "
                    "is computed via an ensemble of five value networks, and that this "
                    "ensemble roughly doubles training wall-clock time compared to the "
                    "baseline. The paper does not test CautiousExplore in a multi-agent "
                    "setting."
                ),
            )
        ],
    ),
]

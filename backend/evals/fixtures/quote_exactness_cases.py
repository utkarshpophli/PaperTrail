"""Hand-labeled quote-exactness cases for ``run_quote_exactness_eval.py``.

Every ``expected_status`` here is a human judgment call, made by reading the
docstring/design of ``app.evidence.verifier`` (docs/AI_PROVIDERS.md's
"quote-exactness verifier") and deciding what a correct classification of
each (source_text, claimed_excerpt) pair *should* be -- not copied from
whatever the function currently outputs. The eval script measures how often
the real ``classify_excerpt`` agrees with these labels; that gap (if any) is
the point of the exercise, not a bug in the fixture.

Categories, per docs/TESTING.md's explicit call-outs plus DATA_MODEL.md's
five ``VerificationStatus`` values:
- exact match (verbatim, case/whitespace-normalized, or a literal truncated
  substring) -> ``verified``
- reordered words (the adversarial case docs/TESTING.md names explicitly) ->
  ``partially_matched``
- word substitution / minor insertion / trailing punctuation difference,
  still recognizably the same sentence -> ``partially_matched``
- near-miss numbers (the other adversarial case docs/TESTING.md names) ->
  must NOT be ``verified``; a changed digit is a substantive factual
  difference, so ``mismatch``
- paraphrase (same idea, materially different wording) -> not ``verified``;
  ``mismatch`` here since the surrounding prose still overlaps a lot
- correct number, wrong surrounding claim (a number matching by coincidence
  doesn't make the sentence around it true) -> ``mismatch``
- genuinely absent (different topic entirely) -> ``not_found``
- no page text / empty page text / whitespace-only excerpt -> ``needs_review``
  (verifier can't reach a conclusion, never defaults to ``verified``)
"""

from dataclasses import dataclass

from app.models.claim import VerificationStatus


@dataclass(frozen=True)
class QuoteExactnessCase:
    id: str
    category: str
    source_text: str | None
    claimed_excerpt: str
    expected_status: VerificationStatus
    note: str


CASES: list[QuoteExactnessCase] = [
    # --- exact match -> verified ---------------------------------------
    QuoteExactnessCase(
        id="exact_match_simple",
        category="exact_match",
        source_text="The model achieves 94.3% accuracy on the test set.",
        claimed_excerpt="The model achieves 94.3% accuracy on the test set.",
        expected_status=VerificationStatus.verified,
        note="Byte-for-byte quote.",
    ),
    QuoteExactnessCase(
        id="exact_match_case_insensitive",
        category="exact_match",
        source_text="Accuracy was 94.3% on the held-out benchmark.",
        claimed_excerpt="accuracy was 94.3% on the held-out benchmark.",
        expected_status=VerificationStatus.verified,
        note="Case differs only; normalization should treat this as identical.",
    ),
    QuoteExactnessCase(
        id="exact_match_whitespace_wrap",
        category="exact_match",
        source_text="The   loss\nconverged to 0.023 after training\nfor 50 epochs.",
        claimed_excerpt="The loss converged to 0.023 after training for 50 epochs.",
        expected_status=VerificationStatus.verified,
        note="PDF-style line-wrap whitespace; same content once normalized.",
    ),
    QuoteExactnessCase(
        id="exact_substring_truncated",
        category="exact_match",
        source_text=(
            "The dataset contains 10,000 labeled images collected from Flickr "
            "and Google Images over two years."
        ),
        claimed_excerpt="The dataset contains 10,000 labeled images collected from Flickr and Google Images",
        expected_status=VerificationStatus.verified,
        note="A shorter, literal, contiguous quote is still a verbatim excerpt.",
    ),
    QuoteExactnessCase(
        id="short_excerpt_exact",
        category="exact_match",
        source_text="We use the Adam optimizer with a learning rate of 1e-4.",
        claimed_excerpt="Adam optimizer",
        expected_status=VerificationStatus.verified,
        note="Short verbatim fragment; still a valid literal substring.",
    ),
    # --- reordered words (adversarial) -> partially_matched -------------
    QuoteExactnessCase(
        id="reordered_words_adjacent_swap",
        category="reordered_words",
        source_text="Our method reduces error significantly compared to previous work.",
        claimed_excerpt="Reduces error our method significantly compared to previous work.",
        expected_status=VerificationStatus.partially_matched,
        note="Same words, same meaning, clause order swapped -- classic 'reordered words' adversarial case.",
    ),
    QuoteExactnessCase(
        id="reordered_words_clause_swap",
        category="reordered_words",
        source_text="Results show significant improvement over baseline models across all tasks.",
        claimed_excerpt="Significant results show improvement over baseline models across all tasks.",
        expected_status=VerificationStatus.partially_matched,
        note="Same multiset of words, different order.",
    ),
    QuoteExactnessCase(
        id="longer_reorder",
        category="reordered_words",
        source_text="The proposed method combines attention pooling with residual connections to stabilize training.",
        claimed_excerpt="Attention pooling combines the proposed method with residual connections to stabilize training.",
        expected_status=VerificationStatus.partially_matched,
        note="Longer sentence, same reordering pattern.",
    ),
    # --- word substitution / minor insertion / punctuation -> partially_matched --
    QuoteExactnessCase(
        id="word_substitution_partial",
        category="near_paraphrase",
        source_text="We evaluate our approach on three benchmark datasets and report consistent gains.",
        claimed_excerpt="We evaluate our approach on several benchmark datasets and report consistent gains.",
        expected_status=VerificationStatus.partially_matched,
        note="One word swapped ('three' -> 'several'), otherwise identical -- lightly mangled, not fabricated.",
    ),
    QuoteExactnessCase(
        id="punctuation_only_diff",
        category="near_paraphrase",
        source_text="The dataset was collected over two years",
        claimed_excerpt="The dataset was collected over two years.",
        expected_status=VerificationStatus.partially_matched,
        note="Trailing period added; not a literal substring but near-identical.",
    ),
    QuoteExactnessCase(
        id="small_word_insertion",
        category="near_paraphrase",
        source_text="The transformer encoder has 12 layers and 8 attention heads.",
        claimed_excerpt="The transformer encoder has 12 layers and 8 very effective attention heads.",
        expected_status=VerificationStatus.partially_matched,
        note="Two extra words inserted mid-sentence; still overwhelmingly the same claim.",
    ),
    # --- near-miss numbers (adversarial) -> must NOT be verified ---------
    QuoteExactnessCase(
        id="near_miss_number_transposed",
        category="near_miss_number",
        source_text="The model achieves 74% accuracy on ImageNet in our experiments.",
        claimed_excerpt="The model achieves 47% accuracy on ImageNet in our experiments.",
        expected_status=VerificationStatus.mismatch,
        note="Transposed digits (74 vs 47) -- a materially different number, must not verify.",
    ),
    QuoteExactnessCase(
        id="near_miss_number_digit_change",
        category="near_miss_number",
        source_text="Test accuracy reached 89.2% after fine-tuning on the target domain.",
        claimed_excerpt="Test accuracy reached 98.2% after fine-tuning on the target domain.",
        expected_status=VerificationStatus.mismatch,
        note="Single-digit swap changes the reported figure; must not verify.",
    ),
    QuoteExactnessCase(
        id="near_miss_number_decimal",
        category="near_miss_number",
        source_text="F1 score improved from 0.71 to 0.78 across all folds of cross-validation.",
        claimed_excerpt="F1 score improved from 0.71 to 0.87 across all folds of cross-validation.",
        expected_status=VerificationStatus.mismatch,
        note="0.78 vs 0.87 -- transposed decimal digits, a real factual change.",
    ),
    QuoteExactnessCase(
        id="fabricated_number_not_in_paper",
        category="near_miss_number",
        source_text="We report a mean squared error of 0.014 on the validation split.",
        claimed_excerpt="We report a mean squared error of 0.081 on the validation split.",
        expected_status=VerificationStatus.mismatch,
        note="Invented figure not present anywhere in the source.",
    ),
    # --- paraphrase / wrong-context -> not verified ----------------------
    QuoteExactnessCase(
        id="paraphrase_not_verbatim",
        category="paraphrase",
        source_text="The proposed algorithm converges within fifty iterations on average across runs.",
        claimed_excerpt="The new algorithm typically converges after about fifty training steps.",
        expected_status=VerificationStatus.mismatch,
        note="Same idea, materially reworded -- not a quotation. Must not be verified.",
    ),
    QuoteExactnessCase(
        id="long_excerpt_minor_insertion",
        category="paraphrase",
        source_text="The transformer encoder has 12 layers and 8 attention heads per layer.",
        claimed_excerpt="The transformer encoder has 12 layers and 8 attention heads per layer, as shown in Table 2.",
        expected_status=VerificationStatus.mismatch,
        note="Trailing clause invented (no 'Table 2' reference in source) -- more than light mangling.",
    ),
    QuoteExactnessCase(
        id="correct_number_wrong_context",
        category="paraphrase",
        source_text=(
            "In our experiments the model reaches 88.5% top-1 accuracy on ImageNet "
            "after 300 epochs of training."
        ),
        claimed_excerpt="The paper claims 88.5% top-1 accuracy on ImageNet obtained after extensive training.",
        expected_status=VerificationStatus.mismatch,
        note="The number happens to match, but the surrounding claim is reworded enough that this "
        "isn't a real quotation -- a right number doesn't excuse a fabricated sentence around it.",
    ),
    # --- genuinely absent -> not_found -----------------------------------
    QuoteExactnessCase(
        id="genuinely_absent_topic",
        category="absent",
        source_text="This section describes our convolutional architecture for image classification on CIFAR-10.",
        claimed_excerpt="The model achieves 99.9% recall on the fraud detection dataset.",
        expected_status=VerificationStatus.not_found,
        note="Completely unrelated claim; the source never discusses fraud detection at all.",
    ),
    QuoteExactnessCase(
        id="different_paper_section",
        category="absent",
        source_text="Related work on graph neural networks spans message passing and spectral methods.",
        claimed_excerpt="We use a ResNet-50 backbone pretrained on ImageNet for all experiments.",
        expected_status=VerificationStatus.not_found,
        note="Plausible-sounding sentence, but this page's text never says it.",
    ),
    QuoteExactnessCase(
        id="absent_completely_different_domain",
        category="absent",
        source_text="We introduce a reinforcement learning agent trained via proximal policy optimization.",
        claimed_excerpt="The survey covers unsupervised clustering techniques for tabular data.",
        expected_status=VerificationStatus.not_found,
        note="Different subfield entirely; no real overlap with the source text.",
    ),
    # --- can't be checked -> needs_review, never verified ----------------
    QuoteExactnessCase(
        id="no_page_text",
        category="unverifiable",
        source_text=None,
        claimed_excerpt="Any excerpt at all.",
        expected_status=VerificationStatus.needs_review,
        note="Cited page was never parsed -- can't reach a conclusion, must not default to verified.",
    ),
    QuoteExactnessCase(
        id="empty_page_text",
        category="unverifiable",
        source_text="   ",
        claimed_excerpt="Any excerpt at all.",
        expected_status=VerificationStatus.needs_review,
        note="Page text is present but blank (e.g. a scanned page with no OCR layer).",
    ),
    QuoteExactnessCase(
        id="whitespace_only_excerpt",
        category="unverifiable",
        source_text="Some real page text that is long enough to matter here.",
        claimed_excerpt="   ",
        expected_status=VerificationStatus.needs_review,
        note="Degenerate excerpt; nothing to verify against.",
    ),
]

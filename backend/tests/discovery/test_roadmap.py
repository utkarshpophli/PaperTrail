"""Unit tests for ``app.discovery.roadmap`` -- prerequisite-depth
sequencing (pure functions) and narrative-overview generation."""

from app.discovery.roadmap import (
    MilestoneDraft,
    compute_concept_depths,
    generate_roadmap_overview,
    sequence_milestones,
)
from app.discovery.schemas import Concept, PrerequisiteEdge, RoadmapOverviewOutput
from app.models.claim import VerificationStatus
from tests.discovery.fake_provider import FakeDiscoveryProvider


def _concept(concept_id: str, name: str) -> Concept:
    return Concept(
        id=concept_id,
        name=name,
        description=f"{name} description",
        source_arxiv_id="2001.00001",
        grounding_excerpt="an excerpt",
        verification_status=VerificationStatus.verified,
    )


def _draft(draft_id: str, title: str, concept_ids: list[str]) -> MilestoneDraft:
    return MilestoneDraft(id=draft_id, paper_id=None, arxiv_id="2001.00001", title=title, concept_ids=concept_ids)


# --- compute_concept_depths --------------------------------------------


def test_compute_concept_depths_no_edges_is_all_zero() -> None:
    concepts = [_concept("c1", "A"), _concept("c2", "B")]

    depths = compute_concept_depths(concepts, [])

    assert depths == {"c1": 0, "c2": 0}


def test_compute_concept_depths_follows_chain() -> None:
    concepts = [_concept("c1", "A"), _concept("c2", "B"), _concept("c3", "C")]
    # c3 requires c2 which requires c1.
    edges = [
        PrerequisiteEdge(concept_id="c2", prerequisite_concept_id="c1"),
        PrerequisiteEdge(concept_id="c3", prerequisite_concept_id="c2"),
    ]

    depths = compute_concept_depths(concepts, edges)

    assert depths == {"c1": 0, "c2": 1, "c3": 2}


def test_compute_concept_depths_breaks_cycles_instead_of_recursing_forever() -> None:
    concepts = [_concept("c1", "A"), _concept("c2", "B")]
    # A cycle: an LLM-proposed prompt-following slip, not a real DAG.
    edges = [
        PrerequisiteEdge(concept_id="c1", prerequisite_concept_id="c2"),
        PrerequisiteEdge(concept_id="c2", prerequisite_concept_id="c1"),
    ]

    depths = compute_concept_depths(concepts, edges)

    # No stack overflow, and every concept gets *some* finite depth.
    assert set(depths.keys()) == {"c1", "c2"}


# --- sequence_milestones -------------------------------------------------


def test_sequence_milestones_orders_by_prerequisite_depth() -> None:
    drafts = [
        _draft("m1", "Advanced Paper", ["c3"]),  # deepest concept
        _draft("m2", "Foundational Paper", ["c1"]),
        _draft("m3", "Intermediate Paper", ["c2"]),
    ]
    depths = {"c1": 0, "c2": 1, "c3": 2}

    milestones = sequence_milestones(drafts, depths)

    assert [m.title for m in milestones] == ["Foundational Paper", "Intermediate Paper", "Advanced Paper"]
    assert [m.order for m in milestones] == [0, 1, 2]


def test_sequence_milestones_first_is_available_rest_are_locked() -> None:
    drafts = [_draft("m1", "First", ["c1"]), _draft("m2", "Second", ["c2"])]
    depths = {"c1": 0, "c2": 1}

    milestones = sequence_milestones(drafts, depths)

    assert milestones[0].status == "available"
    assert milestones[1].status == "locked"


def test_sequence_milestones_ties_keep_original_order() -> None:
    drafts = [_draft("m1", "First", []), _draft("m2", "Second", [])]

    milestones = sequence_milestones(drafts, {})

    assert [m.title for m in milestones] == ["First", "Second"]


# --- generate_roadmap_overview -------------------------------------------


async def test_generate_roadmap_overview_sanitizes_and_returns_text() -> None:
    output = RoadmapOverviewOutput(overview="<script>bad</script>A learning path overview.")
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)
    milestones = sequence_milestones([_draft("m1", "First", ["c1"])], {"c1": 0})
    concepts = [_concept("c1", "Attention")]

    overview = await generate_roadmap_overview(provider, milestones, concepts, beginner=False, model="m")

    assert "<script" not in overview
    assert "A learning path overview." in overview


async def test_generate_roadmap_overview_beginner_mode_adds_instruction_to_prompt() -> None:
    output = RoadmapOverviewOutput(overview="An overview.")
    provider = FakeDiscoveryProvider(lambda prompt, schema: output)
    milestones = sequence_milestones([_draft("m1", "First", ["c1"])], {"c1": 0})
    concepts = [_concept("c1", "Attention")]

    await generate_roadmap_overview(provider, milestones, concepts, beginner=True, model="m")

    assert len(provider.generate_calls) == 1
    prompt, _schema = provider.generate_calls[0]
    assert "beginner" in prompt.lower()

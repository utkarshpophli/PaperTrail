"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ParseStatusIndicator } from "@/components/parse-status-indicator";
import {
  getEvidence,
  getLearning,
  getReport,
  getStory,
  getTechnicalAppendix,
  type ClaimResponse,
} from "@/lib/evidence-api";
import { placeFigures } from "@/lib/figure-placement";
import { getPaper } from "@/lib/papers-api";
import { getFigures, getStorySpec } from "@/lib/story-api";
import { cn } from "@/lib/utils";
import { EvidenceDrawer } from "./evidence-drawer";
import { LabMode } from "./lab-mode";
import { LAB_SECTIONS, type LabSectionId } from "./lab-sections";
import { PaperMap, type PaperMapItem } from "./paper-map";
import { PreviewMode } from "./preview-mode";
import { StoryEmptyState, StoryMode, STORY_SECTION_ID_PREFIX } from "./story-mode";
import { buildCitingSections, replaceClaim, resolveStory, type StudioMode } from "./studio-model";
import { STUDIO_PANEL_ID, StudioTopBar, tabId } from "./studio-top-bar";
import { NO_MISSING_CODES, useLoadable } from "./use-loadable";

const EVIDENCE_MISSING = ["evidence_not_found"];
const STORY_MISSING = ["story_not_found"];
const REPORT_MISSING = ["report_not_found"];
const TECHNICAL_MISSING = ["technical_appendix_not_found"];
const LEARNING_MISSING = ["learning_not_found"];

function claimIdFromHash(): string | null {
  if (typeof window === "undefined") return null;
  const match = /^#claim-(.+)$/.exec(window.location.hash);
  return match ? decodeURIComponent(match[1]) : null;
}

function scrollToId(id: string): void {
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
  document.getElementById(id)?.scrollIntoView?.({ behavior: reduced ? "auto" : "smooth", block: "start" });
}

function StudioMessage({ children }: { children: ReactNode }) {
  return <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-6 py-16">{children}</div>;
}

export function PaperStudio({ paperId }: { paperId: string }) {
  const [reloadKey, setReloadKey] = useState(0);
  const [mode, setMode] = useState<StudioMode>("lab");
  const [hashClaimId] = useState(claimIdFromHash);
  const [labSection, setLabSection] = useState<LabSectionId>(hashClaimId ? "claims" : "overview");
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(hashClaimId);

  const [paper] = useLoadable(useCallback(() => getPaper(paperId), [paperId]), NO_MISSING_CODES);
  const [evidence, setEvidence] = useLoadable(useCallback(() => getEvidence(paperId), [paperId]), EVIDENCE_MISSING, reloadKey);
  const [spec] = useLoadable(useCallback(() => getStorySpec(paperId), [paperId]), STORY_MISSING, reloadKey);
  const [plainStory] = useLoadable(useCallback(() => getStory(paperId), [paperId]), STORY_MISSING, reloadKey);
  const [figures] = useLoadable(useCallback(() => getFigures(paperId), [paperId]), NO_MISSING_CODES, reloadKey);
  const [report] = useLoadable(useCallback(() => getReport(paperId), [paperId]), REPORT_MISSING, reloadKey);
  const [technical] = useLoadable(useCallback(() => getTechnicalAppendix(paperId), [paperId]), TECHNICAL_MISSING, reloadKey);
  const [learning] = useLoadable(useCallback(() => getLearning(paperId), [paperId]), LEARNING_MISSING, reloadKey);

  const evidenceData = evidence.status === "ready" ? evidence.data : null;
  const story = useMemo(() => resolveStory(spec, plainStory), [spec, plainStory]);
  const figureList = useMemo(() => (figures.status === "ready" ? figures.data : []), [figures]);
  const placement = useMemo(
    () =>
      placeFigures(
        story.kind === "typed"
          ? story.spec.sections.map((s) => ({ id: s.id, claim_ids: s.claim_ids, text: `${s.title}\n${s.body}` }))
          : [],
        figureList,
      ),
    [story, figureList],
  );
  const healthSections = useMemo(
    () =>
      buildCitingSections({
        story,
        report: report.status === "ready" ? report.data : [],
        technical: technical.status === "ready" ? technical.data : [],
        learning: learning.status === "ready" ? learning.data : null,
      }),
    [story, report, technical, learning],
  );

  const selectClaim = useCallback((claimId: string) => setSelectedClaimId(claimId), []);
  const closeDrawer = useCallback(() => setSelectedClaimId(null), []);
  const onAnalysisDone = useCallback(() => setReloadKey((key) => key + 1), []);
  const goReanalyze = useCallback(() => {
    setMode("lab");
    setLabSection("reanalyze");
  }, []);

  useEffect(() => {
    const onHashChange = (): void => {
      const id = claimIdFromHash();
      if (id) setSelectedClaimId(id);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const selectedClaim = evidenceData?.claims.find((c) => c.id === selectedClaimId) ?? null;

  const mapItems: PaperMapItem[] =
    mode === "lab"
      ? LAB_SECTIONS.map(({ id, label }) => ({ id, label }))
      : story.kind === "typed"
        ? story.spec.sections.map((s) => ({ id: `${STORY_SECTION_ID_PREFIX}${s.id}`, label: `${s.index_label} ${s.title}`.trim() }))
        : story.kind === "plain"
          ? story.sections.map((s) => ({ id: `${STORY_SECTION_ID_PREFIX}${s.id}`, label: s.title }))
          : [];

  function onClaimUpdated(claim: ClaimResponse): void {
    if (evidence.status === "ready") setEvidence(replaceClaim(evidence.data, claim));
  }

  const title = paper.status === "ready" ? paper.data.title : null;

  function renderBody(): ReactNode {
    if (paper.status !== "ready") return null;
    const claims = evidenceData?.claims ?? [];
    if (mode === "lab") {
      if (evidence.status === "loading") return <p className="m-0 text-body text-ink-soft">Loading evidence…</p>;
      return (
        <div className="flex flex-col gap-4">
          {evidence.status === "error" && (
            <p role="alert" className="m-0 text-body text-mismatch">
              {evidence.message}
            </p>
          )}
          <LabMode
            section={labSection}
            paperId={paperId}
            evidence={evidenceData}
            refreshKey={reloadKey}
            learning={learning}
            healthSections={healthSections}
            figures={figureList}
            unplacedFigures={placement.unplaced}
            figuresError={figures.status === "error" ? figures.message : null}
            selectedClaimId={selectedClaimId}
            onSelectClaim={selectClaim}
            onAnalysisDone={onAnalysisDone}
          />
        </div>
      );
    }
    if (mode === "story") {
      return (
        <div className="mx-auto w-full max-w-3xl">
          <StoryMode
            paperId={paperId}
            paperTitle={paper.data.title}
            story={story}
            claims={claims}
            placement={placement}
            selectedClaimId={selectedClaimId}
            onSelectClaim={selectClaim}
            onGoReanalyze={goReanalyze}
          />
        </div>
      );
    }
    if (story.kind === "typed") {
      return (
        <PreviewMode
          paperId={paperId}
          paper={paper.data}
          spec={story.spec}
          claims={claims}
          placement={placement}
          selectedClaimId={selectedClaimId}
          onSelectClaim={selectClaim}
        />
      );
    }
    if (story.kind === "loading") return <p className="m-0 text-body text-ink-soft">Loading story…</p>;
    return (
      <div className="mx-auto w-full max-w-3xl">
        <StoryEmptyState
          onGoReanalyze={goReanalyze}
          message={
            story.kind === "plain"
              ? "Preview needs an illustrated story; this paper only has a text-only one. Re-analyze to generate visuals."
              : story.kind === "error"
                ? story.message
                : undefined
          }
        />
      </div>
    );
  }

  function renderShell(): ReactNode {
    if (paper.status === "loading") return <StudioMessage><p className="m-0 text-body text-ink-soft">Loading…</p></StudioMessage>;
    if (paper.status !== "ready") {
      return (
        <StudioMessage>
          <p role="alert" className="m-0 text-body text-mismatch">
            {paper.status === "error" ? paper.message : "Paper not found."}
          </p>
          <Link href="/library" className="text-ui-label text-brand hover:underline">
            Back to Library
          </Link>
        </StudioMessage>
      );
    }
    if (paper.data.parse_status !== "parsed") {
      return (
        <StudioMessage>
          <h1 className="m-0 font-display text-h2 font-medium text-ink">{paper.data.title}</h1>
          <ParseStatusIndicator status={paper.data.parse_status} errorMessage={paper.data.parse_error} />
          <p className="m-0 text-body text-ink-soft">
            {paper.data.parse_status === "failed"
              ? "This paper could not be parsed, so it cannot be analyzed."
              : "This paper isn't parsed yet."}
          </p>
          <Link href="/library" className="text-ui-label text-brand hover:underline">
            Back to Library
          </Link>
        </StudioMessage>
      );
    }

    const drawerDocked = mode === "lab";
    return (
      <>
        <div
          className={cn(
            "mx-auto grid w-full flex-1 grid-cols-1 gap-x-8 px-4 pb-16",
            mode === "preview" ? "max-w-6xl" : "max-w-[1500px] min-[980px]:grid-cols-[13rem_minmax(0,1fr)]",
            drawerDocked && "min-[980px]:grid-cols-[13rem_minmax(0,1fr)_21rem]",
          )}
        >
          {mode !== "preview" && (
            <PaperMap
              items={mapItems}
              activeId={mode === "lab" ? labSection : null}
              onSelect={(id) => (mode === "lab" ? setLabSection(id as LabSectionId) : scrollToId(id))}
            />
          )}
          <div role="tabpanel" id={STUDIO_PANEL_ID} aria-labelledby={tabId(mode)} className="min-w-0 pt-4">
            {renderBody()}
          </div>
          {drawerDocked && (
            <div className="pt-4">
              <EvidenceDrawer claim={selectedClaim} paperId={paperId} variant="docked" onClose={closeDrawer} onClaimUpdated={onClaimUpdated} />
            </div>
          )}
        </div>
        {(mode === "story" || mode === "preview") && (
          <EvidenceDrawer claim={selectedClaim} paperId={paperId} variant="overlay" onClose={closeDrawer} onClaimUpdated={onClaimUpdated} />
        )}
      </>
    );
  }

  return (
    <div className="flex min-h-screen flex-1 flex-col bg-background text-ink">
      <StudioTopBar title={title} mode={mode} onModeChange={setMode} />
      {renderShell()}
    </div>
  );
}

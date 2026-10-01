"use client";

import { CodeLinksPanel } from "@/app/(app)/papers/[id]/code-links-panel";
import { ImplementationPlanPanel } from "@/app/(app)/papers/[id]/implementation-plan-panel";
import { OpencodeHandoffPanel } from "@/app/(app)/papers/[id]/opencode-handoff-panel";
import { RepositoryPanel } from "@/app/(app)/papers/[id]/repository-panel";
import type { ClaimResponse } from "@/lib/evidence-api";
import { EmptyNote } from "./lab-parts";

export const CODE_PANELS = [
  { id: "code-repository", label: "Repository" },
  { id: "code-links", label: "Claim-to-code links" },
  { id: "code-plan", label: "Implementation plan" },
  { id: "code-handoff", label: "OpenCode handoff" },
] as const;

interface CodeModeProps {
  paperId: string;
  /** null until the paper has been analyzed. */
  claims: ClaimResponse[] | null;
}

export function CodeMode({ paperId, claims }: CodeModeProps) {
  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h1 className="m-0 font-display text-h2 font-medium tracking-tight text-ink">Code</h1>
        <p className="m-0 text-body text-ink-soft">
          Turn the paper into working code: link a repository, connect claims to the code that implements them, draft an
          implementation plan, or export a handoff for a coding agent. Nothing here runs code from the paper.
        </p>
      </header>
      <div id="code-repository" className="scroll-mt-24">
        <RepositoryPanel paperId={paperId} />
      </div>
      {claims ? (
        <>
          <div id="code-links" className="scroll-mt-24">
            <CodeLinksPanel paperId={paperId} claims={claims} />
          </div>
          <div id="code-plan" className="scroll-mt-24">
            <ImplementationPlanPanel paperId={paperId} claims={claims} />
          </div>
        </>
      ) : (
        <EmptyNote>Claim links and the implementation plan need an analyzed paper. Analyze it from the Lab first.</EmptyNote>
      )}
      <div id="code-handoff" className="scroll-mt-24">
        <OpencodeHandoffPanel paperId={paperId} />
      </div>
    </div>
  );
}

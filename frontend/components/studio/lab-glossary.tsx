"use client";

import type { GlossaryTermResponse } from "@/lib/evidence-api";
import { Card, EmptyNote, LabSection } from "./lab-parts";

export function LabGlossary({ glossary }: { glossary: readonly GlossaryTermResponse[] }) {
  return (
    <LabSection title="Glossary">
      {glossary.length === 0 ? (
        <EmptyNote>No glossary terms were extracted.</EmptyNote>
      ) : (
        <dl className="m-0 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {glossary.map((term) => (
            <Card key={term.id} className="flex flex-col gap-1">
              <dt className="font-display text-h4 font-medium text-ink">{term.term}</dt>
              <dd className="m-0 text-body text-ink-soft">{term.definition}</dd>
              {term.source_page !== null && <dd className="m-0 text-caption text-ink-soft">Page {term.source_page}</dd>}
            </Card>
          ))}
        </dl>
      )}
    </LabSection>
  );
}

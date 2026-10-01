"use client";

import { useParams } from "next/navigation";
import { PaperStudio } from "@/components/studio/paper-studio";

/** The paper studio (Lab / Story / Preview / Code). All behaviour lives in
 * components/studio; this route only supplies the id. Keyed by id so state
 * never leaks between papers. */
export default function PaperStudioPage() {
  const params = useParams<{ id: string }>();
  return <PaperStudio key={params.id} paperId={params.id} />;
}

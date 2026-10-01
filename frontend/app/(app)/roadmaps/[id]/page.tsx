"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ApiRequestError } from "@/lib/api-types";
import { getRoadmap, updateMilestoneStatus, type MilestoneUpdateStatus, type Roadmap } from "@/lib/discovery-api";
import { MilestoneItem } from "./milestone-item";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Could not load roadmap.";
}

export default function RoadmapDetailPage() {
  const params = useParams<{ id: string }>();
  const roadmapId = typeof params.id === "string" ? params.id : "";
  const [roadmap, setRoadmap] = useState<Roadmap | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!roadmapId) return;
    getRoadmap(roadmapId)
      .then(setRoadmap)
      .catch((err: unknown) => setError(errorMessage(err)));
  }, [roadmapId]);

  async function handleStatusChange(milestoneId: string, status: MilestoneUpdateStatus): Promise<void> {
    if (!roadmap) return;
    try {
      const updated = await updateMilestoneStatus(roadmap.id, milestoneId, status);
      setRoadmap(updated);
    } catch (err: unknown) {
      setError(errorMessage(err));
    }
  }

  if (error) {
    return (
      <div className="p-6">
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      </div>
    );
  }

  if (!roadmap) {
    return (
      <div className="flex min-h-[200px] items-center justify-center p-6 text-body text-muted-foreground">
        Loading roadmap…
      </div>
    );
  }

  const orderedMilestones = [...roadmap.milestones].sort((a, b) => a.order - b.order);

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-h1 font-display font-semibold text-foreground">{roadmap.target_description}</h1>
      </div>

      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
        <h2 className="text-h4 font-display font-semibold text-foreground">Overview</h2>
        <p className="whitespace-pre-wrap text-body text-foreground">{roadmap.overview}</p>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-h4 font-display font-semibold text-foreground">Milestones</h2>
        <ol className="flex flex-col gap-3">
          {orderedMilestones.map((milestone) => (
            <MilestoneItem
              key={milestone.id}
              milestone={milestone}
              concepts={roadmap.concepts}
              edges={roadmap.edges}
              onStatusChange={(status) => void handleStatusChange(milestone.id, status)}
            />
          ))}
        </ol>
      </div>
    </div>
  );
}

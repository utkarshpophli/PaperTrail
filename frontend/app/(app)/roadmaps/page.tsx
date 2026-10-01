import { RoadmapCreateForm } from "./roadmap-create-form";
import { RoadmapList } from "./roadmap-list";

export default function RoadmapsPage() {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-h1 font-display font-semibold text-foreground">Roadmaps</h1>
        <p className="text-body text-muted-foreground">
          Generate a guided path of prerequisite concepts and milestone papers for a topic or an existing paper.
        </p>
      </div>

      <RoadmapCreateForm />
      <RoadmapList />
    </div>
  );
}

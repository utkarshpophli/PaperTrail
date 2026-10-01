"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api-types";
import { listCollections, type Collection } from "@/lib/collections-api";
import { promoteLandscape, type LandscapePromoteResponse } from "@/lib/discovery-api";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Could not save to collection.";
}

interface LandscapePromoteProps {
  landscapeId: string;
}

/** "Save to collection" action for a completed Topic Landscape — copies its
 * already-ingested, owned papers into a new or existing Collection
 * (POST /discover/landscape/{id}/promote). Un-ingested candidates are
 * reported back as `skipped_not_ingested`, always shown to the user rather
 * than silently dropped. */
export function LandscapePromote({ landscapeId }: LandscapePromoteProps) {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionsError, setCollectionsError] = useState<string | null>(null);
  const [existingCollectionId, setExistingCollectionId] = useState("");
  const [newCollectionName, setNewCollectionName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LandscapePromoteResponse | null>(null);

  useEffect(() => {
    listCollections()
      .then(setCollections)
      .catch((err: unknown) => setCollectionsError(errorMessage(err)));
  }, []);

  const trimmedNewName = newCollectionName.trim();
  const canSubmit = (existingCollectionId !== "" || trimmedNewName !== "") && !submitting;

  async function handleSave(): Promise<void> {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const response = await promoteLandscape(landscapeId, {
        ...(existingCollectionId ? { collection_id: existingCollectionId } : {}),
        ...(!existingCollectionId && trimmedNewName ? { collection_name: trimmedNewName } : {}),
      });
      setResult(response);
      setNewCollectionName("");
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Save to collection</h2>

      {collectionsError && (
        <p role="alert" className="text-body text-mismatch">
          {collectionsError}
        </p>
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <label className="sr-only" htmlFor="promote-existing-collection">
          Existing collection
        </label>
        <select
          id="promote-existing-collection"
          value={existingCollectionId}
          onChange={(event) => setExistingCollectionId(event.target.value)}
          disabled={submitting}
          className="rounded-md border border-input bg-background px-2 py-1.5 text-body text-foreground"
        >
          <option value="">New collection…</option>
          {collections.map((collection) => (
            <option key={collection.id} value={collection.id}>
              {collection.name}
            </option>
          ))}
        </select>

        {existingCollectionId === "" && (
          <input
            type="text"
            value={newCollectionName}
            onChange={(event) => setNewCollectionName(event.target.value)}
            placeholder="New collection name"
            disabled={submitting}
            className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
          />
        )}

        <Button type="button" onClick={() => void handleSave()} disabled={!canSubmit}>
          {submitting ? "Saving…" : "Save to collection"}
        </Button>
      </div>

      {error && (
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      )}

      {result && (
        <p className="text-body text-foreground">
          {result.added.length} paper{result.added.length === 1 ? "" : "s"} added
          {result.skipped_not_ingested.length > 0 && (
            <>
              , {result.skipped_not_ingested.length} skipped (not yet in your library):{" "}
              {result.skipped_not_ingested.join(", ")}
            </>
          )}
          .
        </p>
      )}
    </div>
  );
}

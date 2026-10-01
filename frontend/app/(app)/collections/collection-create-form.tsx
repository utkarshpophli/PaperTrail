"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api-types";
import { createCollection, type Collection } from "@/lib/collections-api";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Could not create collection.";
}

interface CollectionCreateFormProps {
  onCreated: (collection: Collection) => void;
}

/** Create-collection form: a single name input, same minimal-form shape as
 * every other provider-less create action in this app. */
export function CollectionCreateForm({ onCreated }: CollectionCreateFormProps) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate(): Promise<void> {
    const trimmed = name.trim();
    if (!trimmed) return;
    setSubmitting(true);
    setError(null);
    try {
      const collection = await createCollection(trimmed);
      setName("");
      onCreated(collection);
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Create a collection</h2>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <label className="sr-only" htmlFor="collection-name">
          Collection name
        </label>
        <input
          id="collection-name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Diffusion models"
          disabled={submitting}
          className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
        />
        <Button type="button" onClick={() => void handleCreate()} disabled={!name.trim() || submitting}>
          {submitting ? "Creating…" : "Create collection"}
        </Button>
      </div>

      {error && (
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      )}
    </div>
  );
}

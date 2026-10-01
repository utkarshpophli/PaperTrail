"use client";

import { useEffect, useState } from "react";
import { ApiRequestError } from "@/lib/api-types";
import { listCollections, type Collection } from "@/lib/collections-api";
import { CollectionCreateForm } from "./collection-create-form";
import { CollectionList } from "./collection-list";

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Could not load collections.";
}

export default function CollectionsPage() {
  const [collections, setCollections] = useState<Collection[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCollections()
      .then(setCollections)
      .catch((err: unknown) => setError(errorMessage(err)));
  }, []);

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-h1 font-display font-semibold text-foreground">Collections</h1>
        <p className="text-body text-muted-foreground">Curated lists of your own papers.</p>
      </div>

      <CollectionCreateForm onCreated={(collection) => setCollections((prev) => [...(prev ?? []), collection])} />
      <CollectionList collections={collections} error={error} />
    </div>
  );
}

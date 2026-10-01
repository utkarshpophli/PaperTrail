"use client";

import { useEffect, useState } from "react";
import { ApiRequestError } from "@/lib/api-client";

export type Loadable<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  /** The API answered with one of the caller's "not generated yet" codes. */
  | { status: "missing" }
  | { status: "error"; message: string };

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

export const NO_MISSING_CODES: readonly string[] = [];

/**
 * Small fetch-state hook: the studio only needs load / reload / patch, and
 * the project has no query library installed (no new dependencies this
 * milestone). `load` and `missingCodes` must be referentially stable
 * (useCallback / module constant); `reloadKey` bumps to refetch. A previous
 * result stays visible while a reload is in flight.
 */
export function useLoadable<T>(
  load: () => Promise<T>,
  missingCodes: readonly string[],
  reloadKey = 0,
): [Loadable<T>, (data: T) => void] {
  const [state, setState] = useState<Loadable<T>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    load()
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiRequestError && missingCodes.includes(error.code)) {
          setState({ status: "missing" });
          return;
        }
        setState({ status: "error", message: errorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [load, missingCodes, reloadKey]);

  return [state, (data) => setState({ status: "ready", data })];
}

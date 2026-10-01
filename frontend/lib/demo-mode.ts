export const REPO_URL = "https://github.com/utkarshpophli/PaperTrail";

/** True only in the hosted public demo build. Next inlines NEXT_PUBLIC_* at
 * build time, so this costs nothing at runtime; read per call so tests can
 * stub it. */
export function isDemoMode(): boolean {
  return process.env.NEXT_PUBLIC_DEMO_MODE === "1";
}

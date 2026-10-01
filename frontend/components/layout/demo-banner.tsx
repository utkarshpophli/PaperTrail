import { REPO_URL, isDemoMode } from "@/lib/demo-mode";

/** Shown on every page of the hosted demo: the workspace is shared between
 * visitors, so nobody should mistake it for a private, on-machine install. */
export function DemoBanner() {
  if (!isDemoMode()) return null;
  return (
    <div role="note" className="border-b border-line bg-secondary px-4 py-2 text-center text-caption text-ink-soft">
      <strong className="font-semibold text-ink">Public demo, shared workspace.</strong> Papers added here are visible
      to other visitors and are wiped when the demo restarts. Your API key is sent with each request and never stored.{" "}
      <a href={REPO_URL} className="font-medium text-primary underline-offset-2 hover:underline">
        Run it on your own machine
      </a>{" "}
      for privacy and local models.
    </div>
  );
}

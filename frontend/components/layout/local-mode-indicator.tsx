"use client";

import { useSessionMode } from "@/lib/session-mode-store";

/**
 * Persistent, visible indicator per docs/UI_UX.md ("local-mode sessions are
 * visually distinct") and docs/.claude/rules/ui-design.md. Reflects actual
 * off-machine traffic this session — a cloud provider used OR an external
 * service (arXiv/OpenAlex/GitHub) called (see lib/session-mode-store.ts) —
 * not provider selection — resets on page reload, never persisted.
 */
export function LocalModeIndicator({ collapsed = false }: { collapsed?: boolean }) {
  const mode = useSessionMode();
  const isLocal = mode === "local";
  const label = isLocal ? "local · nothing leaves this machine" : "external · data was sent outside this machine this session";

  return (
    <div
      className="flex items-center gap-2 rounded-md border border-border bg-muted px-2 py-1.5 text-caption text-muted-foreground"
      title={label}
    >
      <span
        className={`size-1.5 shrink-0 rounded-full ${isLocal ? "bg-verified" : "bg-primary"}`}
        aria-hidden="true"
      />
      {!collapsed && <span className="truncate">{label}</span>}
    </div>
  );
}

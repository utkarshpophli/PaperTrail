import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Centered reading-mode variant of the Research Canvas, for future reading
 * surfaces (Paper Reader, etc.) per docs/UI_UX.md. The Canvas is full-bleed
 * by default (see AppShell) — pages opt into this narrower, centered width.
 */
export function ReadingCanvas({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mx-auto w-full max-w-[1120px]", className)}>{children}</div>;
}

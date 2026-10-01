"use client";

import Image from "next/image";
import Link from "next/link";
import { useRef, type KeyboardEvent } from "react";
import { LocalModeIndicator } from "@/components/layout/local-mode-indicator";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { cn } from "@/lib/utils";
import { STUDIO_MODES, type StudioMode } from "./studio-model";

export const tabId = (mode: StudioMode): string => `studio-tab-${mode}`;
export const STUDIO_PANEL_ID = "studio-panel";

interface StudioTopBarProps {
  title: string | null;
  mode: StudioMode;
  onModeChange: (mode: StudioMode) => void;
}

const ACTION_CLASS =
  "rounded-md px-2.5 py-1 text-ui-label font-medium text-ink-soft hover:bg-muted hover:text-ink focus-visible:outline-2 focus-visible:outline-paper-accent";

export function StudioTopBar({ title, mode, onModeChange }: StudioTopBarProps) {
  const tabRefs = useRef<Partial<Record<StudioMode, HTMLButtonElement | null>>>({});

  function onTabKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    const index = STUDIO_MODES.findIndex((m) => m.id === mode);
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    const target = event.key === "Home" ? 0 : event.key === "End" ? STUDIO_MODES.length - 1 : index + step;
    if (event.key !== "Home" && event.key !== "End" && step === 0) return;
    event.preventDefault();
    const next = STUDIO_MODES[(target + STUDIO_MODES.length) % STUDIO_MODES.length].id;
    onModeChange(next);
    tabRefs.current[next]?.focus();
  }

  return (
    <header className="sticky top-0 z-30 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-background/95 px-4 py-2 backdrop-blur">
      <Link href="/" aria-label="Paper Trail home" className="flex items-center gap-2 focus-visible:outline-2 focus-visible:outline-paper-accent">
        <Image src="/logo.png" alt="" width={28} height={28} className="size-7" priority />
        <span className="hidden font-display text-h4 font-medium tracking-tight text-ink sm:inline">Paper Trail</span>
      </Link>

      <div className="min-w-0 flex-1 basis-40">
        <p className="m-0 text-caption uppercase tracking-[0.14em] text-ink-soft">Current paper</p>
        <p className="m-0 truncate font-display text-body font-medium text-ink" title={title ?? undefined}>
          {title ?? "Loading…"}
        </p>
      </div>

      <div role="tablist" aria-label="Studio mode" onKeyDown={onTabKeyDown} className="flex rounded-full border border-line-dark bg-surface p-0.5">
        {STUDIO_MODES.map((m) => {
          const selected = m.id === mode;
          return (
            <button
              key={m.id}
              ref={(el) => {
                tabRefs.current[m.id] = el;
              }}
              type="button"
              role="tab"
              id={tabId(m.id)}
              aria-selected={selected}
              aria-controls={STUDIO_PANEL_ID}
              tabIndex={selected ? 0 : -1}
              onClick={() => onModeChange(m.id)}
              className={cn(
                "rounded-full px-3.5 py-1 text-ui-label font-medium focus-visible:outline-2 focus-visible:outline-paper-accent",
                selected ? "bg-ink text-on-ink" : "text-ink-soft hover:text-ink",
              )}
            >
              {m.label}
            </button>
          );
        })}
      </div>

      <nav aria-label="Studio actions" className="flex items-center gap-1">
        <Link href="/" className={ACTION_CLASS}>
          Home
        </Link>
        <Link href="/library" className={ACTION_CLASS}>
          Library
        </Link>
        <Link href="/" className={cn(ACTION_CLASS, "border border-line-dark bg-surface text-ink")}>
          + New
        </Link>
      </nav>
      <div className="hidden lg:block">
        <LocalModeIndicator />
      </div>
      <div className="lg:hidden">
        <LocalModeIndicator collapsed />
      </div>
      <ThemeToggle />
    </header>
  );
}

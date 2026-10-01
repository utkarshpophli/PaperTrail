"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

type Theme = "light" | "dark";

const STORAGE_KEY = "theme";

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

/** Day/night switch. The theme lives on `<html data-theme>` (set before
 * paint by the script in app/layout.tsx); this flips it and remembers the
 * choice. */
export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, currentTheme, () => "light" as Theme);
  const dark = theme === "dark";

  function toggle(): void {
    const next: Theme = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage blocked (private mode): the switch still works for this visit.
    }
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="Dark mode"
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={toggle}
      className="relative inline-flex h-7 w-[3.25rem] shrink-0 cursor-pointer items-center rounded-full border border-line bg-surface-2 transition-colors hover:border-line-dark focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-paper-accent"
    >
      <Sun aria-hidden="true" className={cn("absolute left-1.5 size-3.5 text-ink-soft transition-opacity", dark ? "opacity-100" : "opacity-0")} />
      <Moon aria-hidden="true" className={cn("absolute right-1.5 size-3.5 text-ink-soft transition-opacity", dark ? "opacity-0" : "opacity-100")} />
      <span
        aria-hidden="true"
        className={cn(
          "flex size-5 items-center justify-center rounded-full bg-surface shadow-sm ring-1 ring-line transition-transform duration-200 ease-out motion-reduce:transition-none",
          dark ? "translate-x-[1.6rem]" : "translate-x-[0.2rem]",
        )}
      >
        {dark ? <Moon className="size-3 text-paper-accent" /> : <Sun className="size-3 text-paper-accent" />}
      </span>
    </button>
  );
}

"use client";

import type { ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { LocalModeIndicator } from "./local-mode-indicator";
import { ThemeToggle } from "./theme-toggle";
import { PRIMARY_NAV, isActivePath, isStudioPath } from "./nav-items";

const LINK = "rounded-md px-3 py-1.5 text-ui-label font-medium transition-colors";

function navLinkClass(active: boolean): string {
  return cn(LINK, active ? "bg-secondary text-ink" : "text-ink-soft hover:bg-secondary hover:text-ink");
}

/**
 * Slim top bar (brand, Home, Library, local-mode indicator). Discover,
 * Roadmaps, Collections and Graph are held back for a later release: their
 * pages still exist but nothing links to them.
 * Paper studio routes (/papers/{id}) render bare: the studio owns its own
 * header, so no chrome is layered on top of it.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (isStudioPath(pathname)) return <>{children}</>;

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="sticky top-0 z-40 border-b border-line bg-surface/90 backdrop-blur">
        <nav aria-label="Primary" className="mx-auto flex h-14 w-full max-w-[1200px] items-center gap-2 px-4 sm:px-6">
          <Link href="/" className="mr-3 flex items-center gap-2 font-display text-h4 font-medium tracking-tight text-ink">
            <Image src="/logo.png" alt="" width={28} height={28} className="size-7" priority />
            Paper Trail
          </Link>
          <div className="flex flex-1 items-center gap-1">
            {PRIMARY_NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActivePath(pathname, item.href) ? "page" : undefined}
                className={navLinkClass(isActivePath(pathname, item.href))}
              >
                {item.label}
              </Link>
            ))}
          </div>
          <span className="hidden md:block">
            <LocalModeIndicator />
          </span>
          <span className="md:hidden">
            <LocalModeIndicator collapsed />
          </span>
          <ThemeToggle />
        </nav>
      </header>
      <main className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col">{children}</main>
    </div>
  );
}

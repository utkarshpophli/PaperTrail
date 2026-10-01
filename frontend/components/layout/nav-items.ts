export interface NavItem {
  href: string;
  label: string;
}

/** Always-visible links in the top bar. */
export const PRIMARY_NAV: readonly NavItem[] = [
  { href: "/", label: "Home" },
  { href: "/library", label: "Library" },
];

/** The paper studio owns its own header, so the shell renders bare there. */
const STUDIO_PATH = /^\/papers\/[^/]+/;

export function isStudioPath(pathname: string): boolean {
  return STUDIO_PATH.test(pathname);
}

/** A link is active on its own path and any sub-path (Home only on "/"). */
export function isActivePath(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

import { describe, expect, it, vi } from "vitest";
import PapersPage from "./page";

const redirect = vi.fn();
vi.mock("next/navigation", () => ({
  redirect: (path: string) => {
    redirect(path);
    throw new Error("NEXT_REDIRECT");
  },
}));

describe("PapersPage", () => {
  it("redirects the old /papers list to /library", () => {
    expect(() => PapersPage()).toThrow("NEXT_REDIRECT");
    expect(redirect).toHaveBeenCalledWith("/library");
  });
});

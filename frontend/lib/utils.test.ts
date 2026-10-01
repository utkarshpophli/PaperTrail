import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("keeps a text color next to one of our custom text sizes", () => {
    expect(cn("bg-primary text-primary-foreground", "text-body")).toBe("bg-primary text-primary-foreground text-body");
  });

  it("still lets a later text size replace an earlier one", () => {
    expect(cn("text-caption", "text-body")).toBe("text-body");
  });
});

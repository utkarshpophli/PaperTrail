import { afterEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  __resetSessionModeForTests,
  markExternalDataSent,
  markProviderUsed,
  useSessionMode,
} from "./session-mode-store";
import type { ProviderCatalogEntry } from "./provider-types";

function provider(auth: ProviderCatalogEntry["auth"]): ProviderCatalogEntry {
  return { id: "p", label: "P", auth, capabilities: [], implemented: true };
}

describe("session-mode-store", () => {
  afterEach(() => {
    __resetSessionModeForTests();
  });

  it("stays local when only local providers are used", () => {
    const { result } = renderHook(() => useSessionMode());
    expect(result.current).toBe("local");

    act(() => {
      markProviderUsed(provider("none"));
      markProviderUsed(provider("none"));
    });

    expect(result.current).toBe("local");
  });

  it("flips to cloud once a cloud provider is used, and never flips back", () => {
    const { result } = renderHook(() => useSessionMode());

    act(() => markProviderUsed(provider("api_key")));
    expect(result.current).toBe("cloud");

    act(() => markProviderUsed(provider("none")));
    expect(result.current).toBe("cloud");
  });

  it("flips to cloud when external data is sent, even though only local providers were used", () => {
    const { result } = renderHook(() => useSessionMode());

    act(() => markProviderUsed(provider("none")));
    expect(result.current).toBe("local");

    act(() => markExternalDataSent());
    expect(result.current).toBe("cloud");
  });

  it("stays flipped after markExternalDataSent, including across a later local-provider use and a repeat call", () => {
    const { result } = renderHook(() => useSessionMode());

    act(() => markExternalDataSent());
    act(() => {
      markProviderUsed(provider("none"));
      markExternalDataSent();
    });

    expect(result.current).toBe("cloud");
  });
});

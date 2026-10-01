import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { LocalModeIndicator } from "./local-mode-indicator";
import { __resetSessionModeForTests, markExternalDataSent, markProviderUsed } from "@/lib/session-mode-store";
import type { ProviderCatalogEntry } from "@/lib/provider-types";

const CLOUD_PROVIDER: ProviderCatalogEntry = {
  id: "google",
  label: "Google Gemini",
  auth: "api_key",
  capabilities: [],
  implemented: true,
};

describe("LocalModeIndicator", () => {
  afterEach(() => {
    __resetSessionModeForTests();
    vi.unstubAllEnvs();
  });

  it("never claims nothing leaves the machine on the hosted demo", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "1");
    render(<LocalModeIndicator />);
    expect(screen.getByText("hosted demo · papers are on a shared server")).toBeInTheDocument();
    expect(screen.queryByText("local · nothing leaves this machine")).not.toBeInTheDocument();
  });

  it("renders the local state by default", () => {
    render(<LocalModeIndicator />);
    expect(screen.getByText("local · nothing leaves this machine")).toBeInTheDocument();
  });

  it("renders the cloud state once a cloud provider has been used", () => {
    markProviderUsed(CLOUD_PROVIDER);
    render(<LocalModeIndicator />);
    expect(screen.getByText("external · data was sent outside this machine this session")).toBeInTheDocument();
    expect(screen.queryByText("local · nothing leaves this machine")).not.toBeInTheDocument();
  });

  it("renders the same external state when only an external service was called (no cloud provider)", () => {
    markExternalDataSent();
    render(<LocalModeIndicator />);
    expect(screen.getByText("external · data was sent outside this machine this session")).toBeInTheDocument();
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { RepositoryPanel } from "./repository-panel";
import { __resetSessionModeForTests, useSessionMode } from "@/lib/session-mode-store";
import {
  deleteRepository,
  detectRepositories,
  getRepositories,
  linkRepository,
  type Repository,
  type RepositoryCandidate,
} from "@/lib/coderesearch-api";

vi.mock("@/lib/coderesearch-api", () => ({
  getRepositories: vi.fn(),
  linkRepository: vi.fn(),
  deleteRepository: vi.fn(),
  detectRepositories: vi.fn(),
}));

const LINKED: Repository = {
  id: "repo-1",
  paper_id: "paper-1",
  url: "https://github.com/owner/repo",
  owner: "owner",
  name: "repo",
  description: "An implementation.",
  stars: 42,
  source: "user_linked",
  confidence: null,
  created_at: "2024-01-01T00:00:00Z",
};

const CANDIDATE: RepositoryCandidate = {
  url: "https://github.com/other/guess",
  owner: "other",
  name: "guess",
  description: "A guessed implementation.",
  stars: 7,
  confidence: 0.4,
};

describe("RepositoryPanel", () => {
  afterEach(() => {
    __resetSessionModeForTests();
  });

  it("lists linked repositories and unlinks one", async () => {
    vi.mocked(getRepositories).mockResolvedValueOnce([LINKED]);
    vi.mocked(deleteRepository).mockResolvedValueOnce(undefined);

    render(<RepositoryPanel paperId="paper-1" />);

    expect(await screen.findByText("owner/repo")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Unlink" }));

    await waitFor(() => expect(deleteRepository).toHaveBeenCalledWith("paper-1", "repo-1"));
    await waitFor(() => expect(screen.queryByText("owner/repo")).not.toBeInTheDocument());
  });

  it("links a repo from the manual form", async () => {
    vi.mocked(getRepositories).mockResolvedValue([]);
    vi.mocked(linkRepository).mockResolvedValueOnce(LINKED);

    render(<RepositoryPanel paperId="paper-1" />);
    await screen.findByText("No repository linked yet.");

    fireEvent.change(screen.getByPlaceholderText("https://github.com/owner/repo"), {
      target: { value: "https://github.com/owner/repo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Link" }));

    await waitFor(() =>
      expect(linkRepository).toHaveBeenCalledWith("paper-1", { url: "https://github.com/owner/repo" }),
    );
  });

  it("shows detected candidates as unconfirmed guesses distinct from linked repos, and links one on demand", async () => {
    vi.mocked(getRepositories).mockResolvedValue([]);
    vi.mocked(detectRepositories).mockResolvedValueOnce([CANDIDATE]);
    vi.mocked(linkRepository).mockResolvedValueOnce({
      ...LINKED,
      id: "repo-2",
      url: CANDIDATE.url,
      owner: CANDIDATE.owner,
      name: CANDIDATE.name,
      source: "detected",
      confidence: null,
    });

    render(<RepositoryPanel paperId="paper-1" />);
    await screen.findByText("No repository linked yet.");

    fireEvent.click(screen.getByRole("button", { name: "Detect implementation" }));

    await screen.findByText("other/guess");
    expect(screen.getByText(/Unconfirmed guess/)).toBeInTheDocument();
    expect(screen.getByText(/Confidence 40%/)).toBeInTheDocument();
    expect(screen.getByText(/Not yet linked/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Link this" }));

    await waitFor(() => expect(linkRepository).toHaveBeenCalledWith("paper-1", { url: CANDIDATE.url }));
  });

  describe("local-mode indicator (GitHub egress)", () => {
    it("marks the session as external when Detect implementation dispatches (no AI provider involved)", async () => {
      vi.mocked(getRepositories).mockResolvedValue([]);
      vi.mocked(detectRepositories).mockResolvedValueOnce([]);
      const session = renderHook(() => useSessionMode());

      render(<RepositoryPanel paperId="paper-1" />);
      await screen.findByText("No repository linked yet.");
      expect(session.result.current).toBe("local");

      fireEvent.click(screen.getByRole("button", { name: "Detect implementation" }));

      await waitFor(() => expect(detectRepositories).toHaveBeenCalled());
      expect(session.result.current).toBe("cloud");
    });

    it("marks the session as external when Link dispatches", async () => {
      vi.mocked(getRepositories).mockResolvedValue([]);
      vi.mocked(linkRepository).mockResolvedValueOnce(LINKED);
      const session = renderHook(() => useSessionMode());

      render(<RepositoryPanel paperId="paper-1" />);
      await screen.findByText("No repository linked yet.");
      fireEvent.change(screen.getByPlaceholderText("https://github.com/owner/repo"), {
        target: { value: "https://github.com/owner/repo" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Link" }));

      await waitFor(() => expect(linkRepository).toHaveBeenCalled());
      expect(session.result.current).toBe("cloud");
    });
  });
});

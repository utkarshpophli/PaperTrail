import { API_URL, apiFetch, apiFetchBlob } from "./api-client";
import type { PageResponse, PaperResponse } from "./paper-types";

export function getPapers(): Promise<PaperResponse[]> {
  return apiFetch<PaperResponse[]>("/papers");
}

export function uploadPaper(file: File): Promise<PaperResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<PaperResponse>("/papers/upload", { method: "POST", body: formData });
}

export type ArxivResolveInput = { arxivId: string } | { arxivTitle: string };

export function resolvePaperFromArxiv(input: ArxivResolveInput): Promise<PaperResponse> {
  const body = "arxivId" in input ? { arxiv_id: input.arxivId } : { arxiv_title: input.arxivTitle };
  return apiFetch<PaperResponse>("/papers/from-arxiv", { method: "POST", body });
}

export function getPaper(paperId: string): Promise<PaperResponse> {
  return apiFetch<PaperResponse>(`/papers/${paperId}`);
}

export function getPaperPage(paperId: string, pageNumber: number): Promise<PageResponse> {
  return apiFetch<PageResponse>(`/papers/${paperId}/pages/${pageNumber}`);
}

export function deletePaper(paperId: string): Promise<void> {
  return apiFetch<void>(`/papers/${paperId}`, { method: "DELETE" });
}

/** image_path is "figures/<filename>" — the route only takes the filename. */
export function getFigureBlob(paperId: string, imagePath: string): Promise<Blob> {
  const filename = imagePath.split("/").pop() ?? imagePath;
  return apiFetchBlob(`/papers/${paperId}/figures/${encodeURIComponent(filename)}`);
}

/** Plain `<img src>` target — the API needs no auth header in local mode, so
 * a figure no longer has to be fetched as a blob first. */
export function figureUrl(paperId: string, filename: string): string {
  return `${API_URL}/papers/${paperId}/figures/${encodeURIComponent(filename)}`;
}

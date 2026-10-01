/**
 * Mirrors backend/app/papers/schemas.py and app/models/paper.py::ParseStatus
 * exactly — read from the FastAPI source, not just docs/API_SPEC.md.
 */

export type ParseStatus = "pending" | "parsing" | "parsed" | "failed";

export interface PaperResponse {
  id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  doi: string | null;
  arxiv_id: string | null;
  parse_status: ParseStatus;
  parse_error: string | null;
  created_at: string;
}

export interface FigureResponse {
  page: number;
  caption: string | null;
  /** Storage-relative path, e.g. "figures/page1_fig0.png". Fetch the actual
   * bytes via GET /papers/{id}/figures/{filename} — see getFigureUrl. */
  image_path: string;
}

export interface PageResponse {
  page_number: number;
  text: string;
  figures: FigureResponse[];
}

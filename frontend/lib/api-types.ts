/** Error envelope shared by every backend route (see backend error handlers). */
export interface ApiErrorBody {
  code: string;
  message: string;
  detail?: unknown;
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail?: unknown;

  constructor(status: number, error: ApiErrorBody) {
    super(error.message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = error.code;
    this.detail = error.detail;
  }
}

export async function parseErrorBody(response: Response): Promise<ApiErrorBody> {
  try {
    const data: unknown = await response.json();
    if (
      typeof data === "object" &&
      data !== null &&
      "error" in data &&
      typeof (data as { error: unknown }).error === "object"
    ) {
      const error = (data as { error: ApiErrorBody }).error;
      if (typeof error.code === "string" && typeof error.message === "string") {
        return error;
      }
    }
  } catch {
    // Response body wasn't JSON — fall through to the generic error below.
  }
  return { code: "unknown_error", message: response.statusText || "Request failed" };
}

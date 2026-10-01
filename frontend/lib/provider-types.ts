/**
 * Mirrors backend/app/providers/registry.py::ProviderCatalogEntry and
 * backend/app/providers/schemas.py exactly — read from the FastAPI source,
 * not just docs/API_SPEC.md.
 */

export type ProviderAuthType = "api_key" | "none";

export interface ProviderCatalogEntry {
  id: string;
  label: string;
  auth: ProviderAuthType;
  capabilities: string[];
  /** Whether build_provider() actually constructs this one yet — the other
   * catalog entries are real rows (catalog is catalog) but verify-connection
   * will 400 for them until their adapters land. */
  implemented: boolean;
}

/**
 * Exactly one of api_key/endpoint is sent, depending on the target
 * provider's `auth` catalog field (enforced server-side in
 * app.providers.router._validate_credential_shape).
 */
export interface VerifyConnectionRequest {
  api_key?: string;
  endpoint?: string;
}

/** Body for POST /providers/{id}/models — same one-of api_key/endpoint shape
 * used by every credential-bearing provider request. */
export type ProviderModelsRequest = VerifyConnectionRequest;

export type ModelKind = "chat" | "embedding" | "other";

export interface ProviderModel {
  id: string;
  label: string;
  context_length: number | null;
  kind: ModelKind;
}

export interface ProviderModelsResponse {
  models: ProviderModel[];
}

export interface TestModelRequest extends VerifyConnectionRequest {
  model: string;
}

export interface TestModelResponse {
  ok: true;
  latency_ms: number;
}

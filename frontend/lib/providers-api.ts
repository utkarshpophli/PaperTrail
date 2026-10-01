import { apiFetch } from "./api-client";
import type {
  ModelKind,
  ProviderCatalogEntry,
  ProviderModelsRequest,
  ProviderModelsResponse,
  TestModelRequest,
  TestModelResponse,
} from "./provider-types";

export function getProviders(): Promise<ProviderCatalogEntry[]> {
  return apiFetch<ProviderCatalogEntry[]>("/providers");
}

export function getProviderModels(
  providerId: string,
  credentials: ProviderModelsRequest,
  signal?: AbortSignal,
  kind: ModelKind = "chat",
): Promise<ProviderModelsResponse> {
  return apiFetch<ProviderModelsResponse>(`/providers/${providerId}/models?kind=${kind}`, {
    method: "POST",
    body: credentials,
    signal,
  });
}

export function testProviderModel(providerId: string, request: TestModelRequest): Promise<TestModelResponse> {
  return apiFetch<TestModelResponse>(`/providers/${providerId}/test-model`, { method: "POST", body: request });
}

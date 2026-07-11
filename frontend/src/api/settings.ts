import type { ApiConfig } from "./client";

const STORAGE_KEY = "ai-testcase-generator.frontend.settings";

export const DEFAULT_API_CONFIG: ApiConfig = {
  baseUrl: "/api/v1",
  apiKey: ""
};

export function loadApiConfig(): ApiConfig {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return DEFAULT_API_CONFIG;
  }
  try {
    return { ...DEFAULT_API_CONFIG, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_API_CONFIG;
  }
}

export function saveApiConfig(config: ApiConfig): ApiConfig {
  const nextConfig = {
    baseUrl: config.baseUrl.trim() || DEFAULT_API_CONFIG.baseUrl,
    apiKey: config.apiKey.trim()
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(nextConfig));
  return nextConfig;
}

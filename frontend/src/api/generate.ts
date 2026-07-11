import type { GenerateRequest } from "./types";

export function normalizeGenerateRequest(request: GenerateRequest): GenerateRequest {
  return {
    description: request.description.trim(),
    max_cases: clampNumber(request.max_cases, 1, 50),
    knowledge_top_k: clampNumber(request.knowledge_top_k, 0, 10),
    include_context: request.include_context,
    focus_types: request.focus_types && request.focus_types.length > 0 ? request.focus_types : null
  };
}

function clampNumber(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) {
    return min;
  }
  return Math.min(Math.max(value, min), max);
}

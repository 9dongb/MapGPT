import type { AnalysisResponse } from "./types";

export async function requestAnalysis(question: string): Promise<AnalysisResponse> {
  const response = await fetch("/api/analyses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? response.statusText);
    throw new Error(`분석 요청 실패 (${response.status}): ${detail}`);
  }
  return response.json();
}

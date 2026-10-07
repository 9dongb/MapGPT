import type { WorkflowError } from "../types";

const STEP_NAMES: Record<string, string> = {
  interpret_query: "질문 해석",
  select_datasets: "데이터 선택",
  build_analysis_plan: "분석 계획 생성",
  validate_plan: "계획 검증",
  load_data: "데이터 조회",
  execute_operations: "GIS 실행",
  validate_result: "결과 검증",
  create_map_layer: "지도 생성",
  generate_explanation: "결과 설명",
};

export function ErrorPanel({ errors, runId }: { errors: WorkflowError[]; runId?: string }) {
  return (
    <section className="card error" role="alert">
      <h2>분석을 완료하지 못했습니다</h2>
      {errors.map((error) => (
        <div key={error.code + error.message}>
          <p>
            <strong>{STEP_NAMES[error.step ?? ""] ?? error.step ?? "요청"}</strong> 단계 · <code>{error.code}</code>
          </p>
          <p>{error.message}</p>
          {error.issues.length > 0 && (
            <ul>
              {error.issues.map((issue) => (
                <li key={issue.code + issue.message}>
                  <code>{issue.code}</code> {issue.path ? <span className="muted">{issue.path}</span> : null} {issue.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
      {runId && <p className="muted provenance">실행 기록: <a href={`/api/analyses/${runId}`} target="_blank" rel="noreferrer">{runId}</a></p>}
    </section>
  );
}

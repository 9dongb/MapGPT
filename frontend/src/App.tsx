import { type FormEvent, useEffect, useState } from "react";
import { requestAnalysis } from "./api";
import { ChoroplethMap } from "./components/ChoroplethMap";
import { ErrorPanel } from "./components/ErrorPanel";
import { Legend } from "./components/Legend";
import { RankingTable } from "./components/RankingTable";
import { ResultDetails } from "./components/ResultDetails";
import { useColorScheme } from "./theme";
import type { AnalysisResponse } from "./types";

const EXAMPLE = "서울에서 어린이 인구 대비 어린이집이 부족한 행정동을 알려줘.";
const STEPS = ["질문 해석", "데이터 선택", "분석 계획", "계획 검증", "GIS 실행", "결과 검증", "지도·설명"];

function useElapsedSeconds(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) return;
    setSeconds(0);
    const timer = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  return seconds;
}

export function App() {
  const scheme = useColorScheme();
  const [question, setQuestion] = useState(EXAMPLE);
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<AnalysisResponse | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const elapsed = useElapsedSeconds(loading);
  const result = response?.result ?? null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || loading) return;
    setLoading(true);
    setRequestError(null);
    try {
      setResponse(await requestAnalysis(question.trim()));
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>MapGPT <span className="muted">공간 분석 Agent</span></h1>
        <form className="question" onSubmit={submit}>
          <input
            aria-label="공간 분석 질문"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={EXAMPLE}
            maxLength={500}
          />
          <button type="submit" disabled={loading || !question.trim()}>
            {loading ? "분석 중…" : "분석"}
          </button>
        </form>
      </header>

      <main className={`content${loading && result ? " stale" : ""}`}>
        <aside className="panel">
          {loading && (
            <section className="card progress" aria-live="polite">
              <div className="spinner" aria-hidden />
              <div>
                <strong>분석 중… {elapsed}초</strong>
                <p className="muted">{STEPS.join(" → ")}</p>
              </div>
            </section>
          )}
          {requestError && (
            <section className="card error" role="alert">
              <h2>요청을 처리하지 못했습니다</h2>
              <p>{requestError}</p>
            </section>
          )}
          {response?.status === "failed" && <ErrorPanel errors={response.errors} runId={response.run_id} />}
          {!response && !loading && !requestError && (
            <section className="card">
              <h2>질문을 입력하세요</h2>
              <p className="muted">
                AI가 질문을 해석해 등록된 공공데이터와 분석 방법을 고르고, 검증된 분석 계획을 PostGIS에서 실행해
                지도와 순위로 보여줍니다.
              </p>
            </section>
          )}
          {result && (
            <>
              <section className="card">
                <h2>요약</h2>
                <p className="summary">{result.summary}</p>
                <p className="metric">
                  <strong>{result.metric.label}</strong> <code>{result.metric.name}</code>
                  <br />
                  <span className="muted">{result.metric.interpretation}</span>
                </p>
              </section>
              <RankingTable result={result} hoveredKey={hoveredKey} onHover={setHoveredKey} />
              <ResultDetails result={result} />
            </>
          )}
        </aside>
        <section className="map-area">
          {result ? (
            <>
              <ChoroplethMap result={result} scheme={scheme} hoveredKey={hoveredKey} onHover={setHoveredKey} />
              <Legend layer={result.map_layer} scheme={scheme} />
            </>
          ) : (
            <div className="map-placeholder muted">분석 결과가 여기에 지도로 표시됩니다</div>
          )}
        </section>
      </main>
    </div>
  );
}

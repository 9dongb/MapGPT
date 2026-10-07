import type { FinalResponse } from "../types";

function List({ items }: { items: string[] }) {
  return (
    <ul>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function ResultDetails({ result }: { result: FinalResponse }) {
  return (
    <>
      <section className="card">
        <h2>사용 데이터와 기준 시점</h2>
        <ul className="datasets">
          {result.datasets.map((d) => (
            <li key={d.dataset_id}>
              <div>
                <strong>{d.title}</strong> <code>{d.dataset_id}</code>
              </div>
              <div className="muted">
                기준 {d.reference_date ?? "미상"} · {d.provider}
                {d.license ? ` · ${d.license}` : ""}
              </div>
              <div className="muted source">{d.source}</div>
            </li>
          ))}
        </ul>
      </section>
      <details className="card" open>
        <summary>분석 방법</summary>
        <ol>
          {result.analysis_method.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </details>
      <details className="card">
        <summary>가정 ({result.assumptions.length})</summary>
        <List items={result.assumptions} />
      </details>
      <details className="card" open>
        <summary>한계 ({result.limitations.length})</summary>
        <List items={result.limitations} />
      </details>
      <p className="muted provenance">
        실행 기록(Provenance): <a href={`/api/analyses/${result.run_id}`} target="_blank" rel="noreferrer">{result.run_id}</a>
      </p>
    </>
  );
}

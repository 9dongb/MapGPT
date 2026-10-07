import { useMemo, useState } from "react";
import { NULL_REASONS, formatValue } from "../theme";
import type { FinalResponse, UnitProperties } from "../types";

interface Props {
  result: FinalResponse;
  hoveredKey: string | null;
  onHover: (key: string | null) => void;
}

interface Row {
  rank: number | null;
  properties: UnitProperties;
}

export function RankingTable({ result, hoveredKey, onHover }: Props) {
  const [showAll, setShowAll] = useState(false);
  const metric = result.metric.name;
  const rankMetric = result.rank_metric;
  const columns = Object.entries(result.metric_labels).filter(([name]) => name !== metric && name !== rankMetric);

  // 표 보기: 지도와 같은 전체 단위를 순위순으로 (값 없는 단위는 맨 뒤)
  const allRows = useMemo<Row[]>(() => {
    const rows = result.map_layer.geojson.features.map((feature) => ({
      rank: rankMetric ? (feature.properties[rankMetric] as number | null) : null,
      properties: feature.properties,
    }));
    return rows.sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.properties.unit_key.localeCompare(b.properties.unit_key));
  }, [result, rankMetric]);
  const rows = showAll ? allRows : allRows.slice(0, result.ranking.length);

  return (
    <section className="card">
      <div className="card-header">
        <h2>{showAll ? `전체 ${allRows.length}개 행정동` : `공급 부족 상위 ${result.ranking.length}개 행정동`}</h2>
        <button type="button" className="link-button" onClick={() => setShowAll((value) => !value)}>
          {showAll ? "상위만 보기" : "전체 표 보기"}
        </button>
      </div>
      <div className={showAll ? "table-wrap table-scroll" : "table-wrap"}>
        <table className="ranking">
          <thead>
            <tr>
              <th scope="col">순위</th>
              <th scope="col">행정동</th>
              <th scope="col" className="num">{result.metric.label}</th>
              {columns.map(([name, label]) => (
                <th key={name} scope="col" className="num">{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ rank, properties }) => {
              const value = properties[metric] as number | null;
              return (
                <tr
                  key={properties.unit_key}
                  className={properties.unit_key === hoveredKey ? "hovered" : undefined}
                  onMouseEnter={() => onHover(properties.unit_key)}
                  onMouseLeave={() => onHover(null)}
                >
                  <td className="num">{rank ?? "–"}</td>
                  <td className="place">
                    <span className="muted">{properties.parent_name}</span> {properties.unit_name}
                  </td>
                  <td className="num strong">
                    {value === null ? (NULL_REASONS[properties.null_reason ?? ""] ?? "값 없음") : formatValue(value)}
                  </td>
                  {columns.map(([name]) => (
                    <td key={name} className="num">{formatValue(properties[name] as number | null)}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

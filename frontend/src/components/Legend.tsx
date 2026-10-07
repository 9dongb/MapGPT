import { type ColorScheme, MAP_CHROME, classColors, formatValue } from "../theme";
import type { MapLayer } from "../types";

/** 분위 구간 범례. 구간은 [경계값 이상, 다음 경계값 미만)이다 (MapLibre step 식과 같음). */
export function Legend({ layer, scheme }: { layer: MapLayer; scheme: ColorScheme }) {
  const { classification } = layer;
  const colors = classColors(scheme, classification.class_count);
  const breaks = classification.breaks;
  const label = (i: number) => {
    if (breaks.length === 0) return `${formatValue(classification.min)}~${formatValue(classification.max)}`;
    if (i === 0) return `${formatValue(breaks[0])} 미만`;
    if (i === breaks.length) return `${formatValue(breaks[i - 1])} 이상`;
    return `${formatValue(breaks[i - 1])}~${formatValue(breaks[i])}`;
  };
  return (
    <div className="legend" aria-label="지도 범례">
      <div className="legend-title">
        {layer.metric_label} <span className="muted">(분위 {colors.length}구간)</span>
      </div>
      <div className="legend-scale">
        {colors.map((color, i) => (
          <div key={color + i} className="legend-class">
            <span className="swatch" style={{ background: color }} />
            <span className="legend-range">{label(i)}</span>
          </div>
        ))}
      </div>
      <div className="legend-ends">
        <span>← 공급 부족</span>
        <span>여유 →</span>
      </div>
      {layer.null_count > 0 && (
        <div className="legend-class">
          <span className="swatch" style={{ background: MAP_CHROME[scheme].noData }} />
          <span className="legend-range">값 없음 {layer.null_count}개</span>
        </div>
      )}
    </div>
  );
}

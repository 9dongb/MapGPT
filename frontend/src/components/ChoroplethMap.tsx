import type { ExpressionSpecification } from "@maplibre/maplibre-gl-style-spec";
import {
  type GeoJSONSource,
  LngLatBounds,
  Map as MapLibreMap,
  type MapLayerMouseEvent,
  NavigationControl,
  Popup,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre v6: 번들러는 내부 worker 경로를 따라가지 못하므로 Vite가 번들한 worker URL을 지정한다.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef } from "react";
import { type ColorScheme, MAP_CHROME, NULL_REASONS, classColors, formatValue } from "../theme";
import type { FinalResponse, UnitProperties } from "../types";

setWorkerUrl(maplibreWorkerUrl);

const SOURCE = "units";
const LAYERS = ["units-fill", "units-separator", "units-hover"];

function fillColor(result: FinalResponse, scheme: ColorScheme): ExpressionSpecification {
  const { metric, classification } = result.map_layer;
  const colors = classColors(scheme, classification.class_count);
  const value: ExpressionSpecification = ["get", metric];
  const stops = classification.breaks.flatMap((limit, i) => [limit, colors[i + 1]]);
  const classified = (stops.length > 0 ? ["step", value, colors[0], ...stops] : colors[0]) as ExpressionSpecification;
  return ["case", ["==", value, null], MAP_CHROME[scheme].noData, classified];
}

// 라벨은 LLM이 만든 문자열이므로 HTML로 넣기 전에 반드시 이스케이프한다.
function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

function tooltipHtml(result: FinalResponse, properties: UnitProperties): string {
  const { metric, metric_label } = result.map_layer;
  const rows = Object.entries(result.metric_labels)
    .filter(([name]) => name !== metric)
    .map(([name, label]) => `<tr><th>${escapeHtml(label)}</th><td>${formatValue(properties[name] as number | null)}</td></tr>`)
    .join("");
  const value = properties[metric] as number | null;
  const valueText = value === null ? (NULL_REASONS[properties.null_reason ?? ""] ?? "값 없음") : formatValue(value);
  const place = escapeHtml(`${properties.parent_name ?? ""} ${properties.unit_name}`);
  return `<div class="tooltip"><strong>${place}</strong>
    <div class="tooltip-value">${escapeHtml(metric_label)}: <b>${valueText}</b></div><table>${rows}</table></div>`;
}

function applyResult(map: MapLibreMap, result: FinalResponse, scheme: ColorScheme) {
  (map.getSource(SOURCE) as GeoJSONSource).setData(result.map_layer.geojson);
  map.setPaintProperty("units-fill", "fill-color", fillColor(result, scheme));
  const bounds = new LngLatBounds();
  for (const feature of result.map_layer.geojson.features) {
    for (const polygon of feature.geometry.coordinates) for (const [x, y] of polygon[0]) bounds.extend([x, y]);
  }
  if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 24, duration: 0 });
}

interface Props {
  result: FinalResponse;
  scheme: ColorScheme;
  hoveredKey: string | null;
  onHover: (key: string | null) => void;
}

export function ChoroplethMap({ result, scheme, hoveredKey, onHover }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const ready = useRef(false);
  const latest = useRef({ result, onHover });
  latest.current = { result, onHover };

  // 배경지도 스타일이 테마마다 다르므로 테마가 바뀌면 지도를 다시 만든다.
  useEffect(() => {
    const chrome = MAP_CHROME[scheme];
    const instance = new MapLibreMap({
      container: container.current!,
      style: chrome.basemapStyle,
      center: [126.98, 37.56],
      zoom: 10,
      attributionControl: { customAttribution: "경계: 통계청 SGIS" },
    });
    const popup = new Popup({ closeButton: false, closeOnClick: false, maxWidth: "280px" });
    instance.addControl(new NavigationControl({ showCompass: false }), "top-right");
    instance.on("load", () => {
      // Choropleth는 도로·면 레이어 위, 마지막 레이블 묶음 아래에 둔다.
      const layers = instance.getStyle().layers;
      const lastShape = layers.findLastIndex((layer) => layer.type !== "symbol");
      const beforeId = layers.slice(lastShape + 1).find((layer) => layer.type === "symbol")?.id;
      instance.addSource(SOURCE, { type: "geojson", data: latest.current.result.map_layer.geojson, promoteId: "unit_key" });
      instance.addLayer({ id: LAYERS[0], type: "fill", source: SOURCE, paint: { "fill-opacity": 0.85 } }, beforeId);
      instance.addLayer(
        { id: LAYERS[1], type: "line", source: SOURCE, paint: { "line-width": 0.8, "line-color": chrome.separator } },
        beforeId,
      );
      instance.addLayer(
        {
          id: LAYERS[2],
          type: "line",
          source: SOURCE,
          paint: {
            "line-color": chrome.hover,
            "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 2.5, 0],
          },
        },
        beforeId,
      );
      ready.current = true;
      applyResult(instance, latest.current.result, scheme);
    });
    instance.on("mousemove", LAYERS[0], (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      instance.getCanvas().style.cursor = "pointer";
      latest.current.onHover(feature.properties.unit_key as string);
      popup.setLngLat(event.lngLat).setHTML(tooltipHtml(latest.current.result, feature.properties as UnitProperties)).addTo(instance);
    });
    instance.on("mouseleave", LAYERS[0], () => {
      instance.getCanvas().style.cursor = "";
      latest.current.onHover(null);
      popup.remove();
    });
    map.current = instance;
    return () => {
      ready.current = false;
      map.current = null;
      instance.remove();
    };
  }, [scheme]);

  // 새 분석 결과 반영
  useEffect(() => {
    if (map.current && ready.current) applyResult(map.current, result, scheme);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  // 표 ↔ 지도 hover 연동
  useEffect(() => {
    const instance = map.current;
    if (!instance || !ready.current || hoveredKey === null) return;
    instance.setFeatureState({ source: SOURCE, id: hoveredKey }, { hover: true });
    return () => {
      if (instance.getSource(SOURCE)) instance.setFeatureState({ source: SOURCE, id: hoveredKey }, { hover: false });
    };
  }, [hoveredKey]);

  return <div ref={container} className="map" role="img" aria-label={`${result.map_layer.metric_label} Choropleth 지도`} />;
}

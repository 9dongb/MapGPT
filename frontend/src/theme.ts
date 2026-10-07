import { useEffect, useState } from "react";

export type ColorScheme = "light" | "dark";

// 5분위 단일 색상(blue) ordinal 램프. 인덱스 0 = 값이 가장 작은 구간(공급 부족)을 가장 눈에 띄게 둔다.
// 라이트는 진할수록, 다크는 밝을수록 부족. dataviz validate_palette.js --ordinal 통과.
export const CLASS_COLORS: Record<ColorScheme, string[]> = {
  light: ["#104281", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef"],
  dark: ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"],
};

// 배경지도: OpenFreeMap (API 키 불필요, © OpenMapTiles · OpenStreetMap)
export const MAP_CHROME: Record<ColorScheme, { noData: string; separator: string; hover: string; basemapStyle: string }> = {
  light: {
    noData: "#c3c2b7",
    separator: "#fcfcfb",
    hover: "#0b0b0b",
    basemapStyle: "https://tiles.openfreemap.org/styles/positron",
  },
  dark: {
    noData: "#383835",
    separator: "#1a1a19",
    hover: "#ffffff",
    basemapStyle: "https://tiles.openfreemap.org/styles/dark",
  },
};

/** 구간 수가 5보다 적을 때(동일 값이 많을 때)도 램프 양 끝을 유지하도록 색을 고른다. */
export function classColors(scheme: ColorScheme, classCount: number): string[] {
  const ramp = CLASS_COLORS[scheme];
  if (classCount <= 1) return [ramp[2]];
  return Array.from({ length: classCount }, (_, i) => ramp[Math.round((i * (ramp.length - 1)) / (classCount - 1))]);
}

export function useColorScheme(): ColorScheme {
  const query = "(prefers-color-scheme: dark)";
  const [scheme, setScheme] = useState<ColorScheme>(() => (window.matchMedia(query).matches ? "dark" : "light"));
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setScheme(media.matches ? "dark" : "light");
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return scheme;
}

export function formatValue(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "–";
  return Number.isInteger(value) ? value.toLocaleString("ko-KR") : value.toLocaleString("ko-KR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export const NULL_REASONS: Record<string, string> = {
  denominator_zero: "분모(인구)가 0",
  denominator_missing: "인구 자료 없음",
  numerator_missing: "시설 자료 없음",
  no_matching_records: "자료 없음",
  input_null: "지표 값 없음",
};

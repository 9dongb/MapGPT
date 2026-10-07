"""어린이집 Adapter: 서울 열린데이터광장 OpenAPI ChildCareInfo."""

import json
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any

SERVICE = "ChildCareInfo"
PAGE_SIZE = 1000  # 서울 OpenAPI 1회 최대 요청 건수


class SeoulApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class FacilityRecord:
    facility_id: str
    name: str
    facility_type: str | None
    status: str
    declared_sigungu_cd: str  # STCODE 앞 5자리 = 신고 시군구 코드
    latitude: float | None
    longitude: float | None
    reference_date: date


def fetch_rows(api_key: str, timeout: float = 30.0) -> list[dict[str, Any]]:
    """전체 원본 행을 페이지 단위로 수집한다. 인증키는 로그·예외 메시지에 남기지 않는다."""
    rows: list[dict[str, Any]] = []
    total: int | None = None
    start = 1
    while total is None or start <= total:
        end = start + PAGE_SIZE - 1
        url = f"http://openapi.seoul.go.kr:8088/{api_key}/json/{SERVICE}/{start}/{end}/"
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
        body = payload.get(SERVICE)
        if body is None:
            result = payload.get("RESULT", {})
            raise SeoulApiError(f"서울 OpenAPI 오류 {result.get('CODE')}: {result.get('MESSAGE')}")
        if body["RESULT"]["CODE"] != "INFO-000":
            raise SeoulApiError(f"서울 OpenAPI 오류 {body['RESULT']['CODE']}: {body['RESULT']['MESSAGE']}")
        total = int(body["list_total_count"])
        rows.extend(body["row"])
        start = end + 1
    if len(rows) != total:
        raise SeoulApiError(f"수집 건수({len(rows)})가 전체 건수({total})와 다릅니다")
    return rows


def parse_facilities(rows: list[dict[str, Any]]) -> list[FacilityRecord]:
    return [
        FacilityRecord(
            facility_id=row["STCODE"],
            name=row["CRNAME"].strip(),
            facility_type=row["CRTYPENAME"].strip() or None,
            status=row["CRSTATUSNAME"].strip(),
            declared_sigungu_cd=row["STCODE"][:5],
            latitude=_to_coordinate(row["LA"]),
            longitude=_to_coordinate(row["LO"]),
            reference_date=date.fromisoformat(row["DATASTDRDT"]),
        )
        for row in rows
    ]


def _to_coordinate(value: str | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number != 0 else None

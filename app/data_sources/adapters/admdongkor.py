"""행정동 경계 Adapter: vuski/admdongkor GeoJSON (통계청 SGIS 기반, EPSG:4326)."""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

VERSION = "20260701"
FILE_NAME = f"HangJeongDong_ver{VERSION}.geojson"
DOWNLOAD_URL = f"https://raw.githubusercontent.com/vuski/admdongkor/master/ver{VERSION}/{FILE_NAME}"

_ACCEPTED_CRS = {"urn:ogc:def:crs:OGC:1.3:CRS84", "EPSG:4326", "urn:ogc:def:crs:EPSG::4326"}


@dataclass(frozen=True)
class BoundaryRecord:
    adm_cd: str
    adm_nm: str
    sido_cd: str
    sido_nm: str
    sigungu_cd: str
    sigungu_nm: str
    geometry: dict[str, Any]


def reference_date_from_name(path: Path) -> date:
    match = re.search(r"ver(\d{8})", path.name)
    if not match:
        raise ValueError(f"파일명에서 경계 버전(verYYYYMMDD)을 찾을 수 없습니다: {path.name}")
    raw = match.group(1)
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))


def read_boundaries(path: Path, sido_code: str) -> list[BoundaryRecord]:
    collection = json.loads(path.read_text(encoding="utf-8"))
    if collection.get("type") != "FeatureCollection":
        raise ValueError("행정동 경계 파일이 GeoJSON FeatureCollection이 아닙니다")
    crs = (collection.get("crs") or {}).get("properties", {}).get("name", "urn:ogc:def:crs:OGC:1.3:CRS84")
    if crs not in _ACCEPTED_CRS:
        raise ValueError(f"지원하지 않는 경계 CRS입니다: {crs}")

    records: list[BoundaryRecord] = []
    seen: set[str] = set()
    for feature in collection["features"]:
        props = feature["properties"]
        if props["sido"] != sido_code:
            continue
        adm_cd = props["adm_cd2"]
        if not re.fullmatch(r"\d{10}", adm_cd):
            raise ValueError(f"행정기관코드 형식이 아닙니다: {adm_cd}")
        if adm_cd in seen:
            raise ValueError(f"행정동 코드가 중복됩니다: {adm_cd}")
        seen.add(adm_cd)
        records.append(
            BoundaryRecord(
                adm_cd=adm_cd,
                adm_nm=props["adm_nm"].split()[-1],
                sido_cd=props["sido"],
                sido_nm=props["sidonm"],
                sigungu_cd=props["sgg"],
                sigungu_nm=props["sggnm"],
                geometry=feature["geometry"],
            )
        )
    return records

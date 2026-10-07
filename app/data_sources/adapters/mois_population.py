"""연령별 인구 Adapter: 행정안전부 지역별(행정동) 성별 연령별 주민등록 인구수 CSV (wide 형식, cp949)."""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FILE_NAME = "mois_population_by_age_20260930.csv"
# 공공데이터포털 15097972 파일데이터 (2026-09-30 기준). 매월 갱신되며 갱신 시 파일 ID가 바뀐다.
DOWNLOAD_URL = "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000007706226&fileDetailSn=1"

_AGE_COLUMN = re.compile(r"^(\d+)세(이상)?\s*(남자|여자)$")


@dataclass(frozen=True)
class PopulationRecord:
    adm_cd: str
    age: int
    population: int
    reference_date: date


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("인구 CSV 인코딩을 판별할 수 없습니다 (utf-8 / cp949 아님)")


def read_population(path: Path, sido_code: str) -> list[PopulationRecord]:
    reader = csv.reader(io.StringIO(_decode(path.read_bytes())))
    header = next(reader)
    index = {name: i for i, name in enumerate(header)}
    for required in ("행정기관코드", "기준연월", "계"):
        if required not in index:
            raise ValueError(f"인구 CSV에 '{required}' 컬럼이 없습니다")

    # 연령 컬럼 → (age, 성별) 위치. 110세이상은 age=110으로 둔다.
    age_columns: dict[int, list[int]] = {}
    for name, i in index.items():
        match = _AGE_COLUMN.match(name)
        if match:
            age_columns.setdefault(int(match.group(1)), []).append(i)
    if sorted(age_columns) != list(range(111)) or any(len(cols) != 2 for cols in age_columns.values()):
        raise ValueError("인구 CSV의 연령 컬럼(0세~110세이상, 남/여)이 예상과 다릅니다")

    records: list[PopulationRecord] = []
    for row in reader:
        adm_cd = row[index["행정기관코드"]]
        if not adm_cd.startswith(sido_code):
            continue
        reference_date = date.fromisoformat(row[index["기준연월"]])
        by_age = {age: sum(_to_int(row[i]) for i in cols) for age, cols in age_columns.items()}
        total = _to_int(row[index["계"]])
        if sum(by_age.values()) != total:
            raise ValueError(f"{adm_cd}: 연령별 인구 합({sum(by_age.values())})이 계({total})와 다릅니다")
        records.extend(
            PopulationRecord(adm_cd=adm_cd, age=age, population=population, reference_date=reference_date)
            for age, population in sorted(by_age.items())
        )
    return records


def _to_int(value: str) -> int:
    number = int(value.replace(",", "").strip() or 0)
    if number < 0:
        raise ValueError(f"인구 값이 음수입니다: {value}")
    return number

"""운영 CLI: python -m app.cli <command>"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

from app.catalog.catalog import sync_catalog_embeddings
from app.config import Settings, get_settings
from app.data_sources import ingest
from app.data_sources.adapters import admdongkor, mois_population, seoul_childcare
from app.db import connect, init_schema
from app.domain.catalog import DatasetMetadata
from app.domain.state import AgentState
from app.llm.base import LLMError
from app.llm.embeddings import EmbeddingError
from app.llm.factory import create_embedder, create_llm
from app.workflows.analysis_workflow import AnalysisWorkflow

DAYCARE_CACHE_PREFIX = "seoul_childcare_"


def _daycare_rows(settings: Settings, refresh: bool) -> list[dict[str, Any]]:
    cached = sorted(settings.raw_data_dir.glob(f"{DAYCARE_CACHE_PREFIX}*.json"))
    if cached and not refresh:
        print(f"어린이집 원본 캐시 사용: {cached[-1].name}")
        return json.loads(cached[-1].read_text(encoding="utf-8"))
    if settings.seoul_open_api_key is None:
        raise SystemExit("SEOUL_OPEN_API_KEY가 설정되지 않았습니다 (.env)")
    rows = seoul_childcare.fetch_rows(settings.seoul_open_api_key.get_secret_value())
    path = settings.raw_data_dir / f"{DAYCARE_CACHE_PREFIX}{date.today():%Y%m%d}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"어린이집 원본 {len(rows)}건 수집 → {path.name}")
    return rows


def _require(path: Path) -> Path:
    if not path.exists():
        raise SystemExit(f"원본 파일이 없습니다: {path} (python -m app.cli download)")
    return path


def _report(metadata: DatasetMetadata) -> None:
    print(
        f"[{metadata.dataset_id}] 기준일 {metadata.temporal.reference_date}, "
        f"feature {metadata.spatial.feature_count}, bbox {metadata.spatial.bbox}"
    )
    for note in metadata.quality_notes:
        print(f"  - {note}")


def _print_run(state: AgentState) -> None:
    print(f"run_id: {state.run_id}\nstatus: {state.status} (LLM {state.llm_provider}/{state.llm_model})")
    for error in state.errors:
        print(f"[실패] {error.step} {error.code}: {error.message}")
        for issue in error.issues:
            print(f"  - [{issue.code}] {issue.path or '-'}: {issue.message}")
    response = state.final_response
    if response is None:
        return
    print(f"\n{response.summary}\n\n[{response.metric.label}] {response.metric.interpretation}")
    for item in response.ranking:
        print(f"{item.rank:>3}. {item.parent_name} {item.unit_name}: {item.value:.2f}")
    print("\n한계:")
    for limitation in response.limitations:
        print(f"  - {limitation}")


def _sync_embeddings(conn: psycopg.Connection, settings: Settings, refresh: bool) -> None:
    embedder = create_embedder(settings)
    updated = sync_catalog_embeddings(conn, embedder, refresh)
    print(f"카탈로그 임베딩({embedder.model}) 갱신: {', '.join(updated) if updated else '변경 없음'}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="DB 스키마 생성 (반복 실행 가능)")
    commands.add_parser("download", help="행정동 경계·인구 원본 파일 다운로드 (data/raw)")
    ingest_parser = commands.add_parser("ingest", help="원본을 내부 표준 Dataset으로 적재")
    ingest_parser.add_argument("dataset", choices=["all", "emd_boundary", "population_by_age", "daycare_facility"])
    ingest_parser.add_argument("--refresh", action="store_true", help="어린이집 API 캐시를 무시하고 다시 수집")
    embed_parser = commands.add_parser("embed-catalog", help="Dataset 검색용 카탈로그 임베딩 갱신 (pgvector)")
    embed_parser.add_argument("--refresh", action="store_true", help="변경 여부와 관계없이 모두 다시 임베딩")
    analyze_parser = commands.add_parser("analyze", help="자연어 질문을 분석 워크플로로 실행")
    analyze_parser.add_argument("question")
    args = parser.parse_args(argv)

    settings = get_settings()
    raw = settings.raw_data_dir

    if args.command == "download":
        for url, name in (
            (admdongkor.DOWNLOAD_URL, admdongkor.FILE_NAME),
            (mois_population.DOWNLOAD_URL, mois_population.FILE_NAME),
        ):
            path = ingest.download(url, raw / name)
            print(f"{path.name}: {path.stat().st_size:,} bytes")
        return
    if args.command == "analyze":
        try:
            llm, embedder = create_llm(settings), create_embedder(settings)
        except (LLMError, EmbeddingError) as error:
            raise SystemExit(str(error)) from error
        with ConnectionPool(settings.database_url, min_size=1, max_size=2) as pool:
            _print_run(AnalysisWorkflow(llm, pool, embedder).run(args.question))
        return

    with connect(settings.database_url) as conn:
        if args.command == "init-db":
            init_schema(conn)
            print("스키마 적용 완료")
        elif args.command == "embed-catalog":
            try:
                _sync_embeddings(conn, settings, args.refresh)
            except EmbeddingError as error:
                raise SystemExit(str(error)) from error
        elif args.command == "ingest":
            targets = (
                ["emd_boundary", "population_by_age", "daycare_facility"] if args.dataset == "all" else [args.dataset]
            )
            for target in targets:
                if target == "emd_boundary":
                    _report(ingest.ingest_boundary(conn, _require(raw / admdongkor.FILE_NAME)))
                elif target == "population_by_age":
                    _report(ingest.ingest_population(conn, _require(raw / mois_population.FILE_NAME)))
                else:
                    _report(ingest.ingest_daycare(conn, _daycare_rows(settings, args.refresh)))
            # 메타데이터가 바뀌었으니 검색 임베딩도 맞춘다. 실패해도 적재 결과는 유지된다.
            try:
                _sync_embeddings(conn, settings, refresh=False)
            except EmbeddingError as error:
                print(f"카탈로그 임베딩을 갱신하지 못했습니다: {error}")
                print("  Dataset 검색 전에 python -m app.cli embed-catalog 를 실행하세요")


if __name__ == "__main__":
    main(sys.argv[1:])

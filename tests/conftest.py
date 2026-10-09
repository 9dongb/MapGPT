import os

import psycopg
import pytest
from psycopg import conninfo, sql

from app.db import init_schema

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://mapgpt:mapgpt@localhost:5432/mapgpt_test")
_TABLES = (
    "analysis.result",
    "analysis.run",
    "catalog.dataset_embedding",
    "catalog.dataset",
    "datasets.emd_boundary",
    "datasets.population_by_age",
    "datasets.daycare_facility",
)


def _ensure_database(url: str) -> None:
    params = conninfo.conninfo_to_dict(url)
    name = params.pop("dbname")
    with psycopg.connect(conninfo.make_conninfo(**params, dbname="postgres"), autocommit=True) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is None:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def database_url() -> str:
    try:
        _ensure_database(TEST_DATABASE_URL)
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            # 스키마가 바뀌어도 테스트가 최신 DDL로 돌도록 매 세션 새로 만든다.
            conn.execute("DROP SCHEMA IF EXISTS analysis, catalog, datasets CASCADE")
            conn.commit()
            init_schema(conn)
    except psycopg.OperationalError as error:
        message = f"PostGIS 테스트 DB에 연결할 수 없습니다: {error}. docker compose up -d 후 다시 실행하세요"
        # 작업 후 검증(scripts/check.py)에서는 DB가 없어 skip된 테스트를 통과로 오인하지 않게 실패로 처리한다.
        if os.environ.get("MAPGPT_REQUIRE_DB") == "1":
            pytest.fail(message, pytrace=False)
        pytest.skip(message)
    return TEST_DATABASE_URL


@pytest.fixture
def conn(database_url: str):
    with psycopg.connect(database_url) as connection:
        connection.execute(
            sql.SQL("TRUNCATE {}").format(sql.SQL(", ").join(sql.Identifier(*table.split(".")) for table in _TABLES))
        )
        connection.commit()
        yield connection

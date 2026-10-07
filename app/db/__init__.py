from importlib.resources import files

import psycopg


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url)


def init_schema(conn: psycopg.Connection) -> None:
    """스키마 DDL을 적용한다. 반복 실행해도 안전하다."""
    ddl = files("app.db").joinpath("schema.sql").read_text(encoding="utf-8")
    with conn.transaction():
        conn.execute(ddl)

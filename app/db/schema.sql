-- MapGPT MVP 스키마 (반복 실행 가능)
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS datasets;
CREATE SCHEMA IF NOT EXISTS analysis;

-- Dataset Catalog: DatasetMetadata 전체 (적재 통계·품질 기록 포함)
CREATE TABLE IF NOT EXISTS catalog.dataset (
    dataset_id text PRIMARY KEY,
    metadata   jsonb NOT NULL,
    loaded_at  timestamptz NOT NULL
);

-- 내부 표준 Dataset: 행정동 경계
CREATE TABLE IF NOT EXISTS datasets.emd_boundary (
    adm_cd     text PRIMARY KEY,
    adm_nm     text NOT NULL,
    sido_cd    text NOT NULL,
    sido_nm    text NOT NULL,
    sigungu_cd text NOT NULL,
    sigungu_nm text NOT NULL,
    geom       geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS emd_boundary_geom_idx ON datasets.emd_boundary USING gist (geom);

-- 내부 표준 Dataset: 행정동별 1세 단위 인구 (long 형식)
CREATE TABLE IF NOT EXISTS datasets.population_by_age (
    adm_cd         text NOT NULL,
    age            integer NOT NULL CHECK (age >= 0),
    population     integer NOT NULL CHECK (population >= 0),
    reference_date date NOT NULL,
    PRIMARY KEY (adm_cd, age)
);

-- 내부 표준 Dataset: 운영 중인 어린이집 위치 (기준 시점은 catalog.dataset의 temporal에 기록)
CREATE TABLE IF NOT EXISTS datasets.daycare_facility (
    facility_id   text PRIMARY KEY,
    name          text NOT NULL,
    facility_type text,
    latitude      double precision NOT NULL,
    longitude     double precision NOT NULL,
    geom          geometry(Point, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS daycare_facility_geom_idx ON datasets.daycare_facility USING gist (geom);

-- Provenance: 분석 실행 기록
CREATE TABLE IF NOT EXISTS analysis.run (
    run_id        uuid PRIMARY KEY,
    question      text NOT NULL,
    status        text NOT NULL,
    analysis_plan jsonb,
    datasets      jsonb,
    operations    jsonb,
    crs           text,
    result_id     uuid,
    llm_provider  text,
    llm_model     text,
    errors        jsonb,
    state         jsonb NOT NULL,
    started_at    timestamptz NOT NULL,
    finished_at   timestamptz
);

CREATE TABLE IF NOT EXISTS analysis.result (
    result_id  uuid PRIMARY KEY,
    run_id     uuid NOT NULL REFERENCES analysis.run (run_id),
    response   jsonb NOT NULL,
    created_at timestamptz NOT NULL
);

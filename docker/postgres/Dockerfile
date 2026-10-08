# PostGIS(공간 연산) + pgvector(Dataset 메타데이터 유사도 검색)
# postgis/postgis 공식 이미지는 amd64 전용이라, 같은 메인테이너의 multi-arch 빌드를 기반으로 한다.
FROM imresamu/postgis:17-3.5

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-pgvector \
    && rm -rf /var/lib/apt/lists/*

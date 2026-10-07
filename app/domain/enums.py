from enum import StrEnum


class AnalysisIntent(StrEnum):
    SUPPLY_DEMAND_GAP = "supply_demand_gap"


class SpatialLevel(StrEnum):
    SIDO = "sido"
    SIGUNGU = "sigungu"
    EMD = "emd"


class GeometryType(StrEnum):
    POINT = "Point"
    POLYGON = "Polygon"
    MULTIPOLYGON = "MultiPolygon"


class DataType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    GEOMETRY = "geometry"


class SemanticType(StrEnum):
    ADMINISTRATIVE_CODE = "administrative_code"
    ADMINISTRATIVE_NAME = "administrative_name"
    SIDO_CODE = "sido_code"
    SIDO_NAME = "sido_name"
    SIGUNGU_CODE = "sigungu_code"
    SIGUNGU_NAME = "sigungu_name"
    AGE = "age"
    POPULATION = "population"
    FACILITY_ID = "facility_id"
    FACILITY_NAME = "facility_name"
    FACILITY_TYPE = "facility_type"
    LATITUDE = "latitude"
    LONGITUDE = "longitude"
    REFERENCE_DATE = "reference_date"
    GEOMETRY = "geometry"


class FilterOperator(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    BETWEEN = "between"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class LogicalOperator(StrEnum):
    AND = "and"
    OR = "or"
    NOT = "not"


class AggregationFunction(StrEnum):
    COUNT = "count"
    SUM = "sum"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class MapType(StrEnum):
    CHOROPLETH = "choropleth"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WorkflowStep(StrEnum):
    INTERPRET_QUERY = "interpret_query"
    SELECT_DATASETS = "select_datasets"
    BUILD_ANALYSIS_PLAN = "build_analysis_plan"
    VALIDATE_PLAN = "validate_plan"
    LOAD_DATA = "load_data"
    EXECUTE_OPERATIONS = "execute_operations"
    VALIDATE_RESULT = "validate_result"
    CREATE_MAP_LAYER = "create_map_layer"
    GENERATE_EXPLANATION = "generate_explanation"

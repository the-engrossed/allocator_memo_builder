from enum import StrEnum


class AnalysisStatus(StrEnum):
    INVALID = "invalid"
    NEEDS_REVIEW = "needs_review"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    VALID = "valid"


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueCode(StrEnum):
    MISSING_COLUMN = "MISSING_COLUMN"
    INVALID_PERIOD = "INVALID_PERIOD"
    INVALID_RETURN = "INVALID_RETURN"
    DUPLICATE_PERIOD = "DUPLICATE_PERIOD"
    MISSING_MONTHS = "MISSING_MONTHS"
    SHORT_HISTORY = "SHORT_HISTORY"
    CONFLICTING_METADATA = "CONFLICTING_METADATA"
    RETURN_UNIT_INFERRED = "RETURN_UNIT_INFERRED"


class ReturnInputUnit(StrEnum):
    DECIMAL = "decimal"
    PERCENT = "percent"

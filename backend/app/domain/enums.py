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
    RETURN_OUT_OF_RANGE = "RETURN_OUT_OF_RANGE"
    INVALID_METADATA = "INVALID_METADATA"
    SMOOTH_RETURNS = "SMOOTH_RETURNS"
    FUND_ID_MISMATCH = "FUND_ID_MISMATCH"
    INCONSISTENT_DATE_RANGE = "INCONSISTENT_DATE_RANGE"
    COMMON_WINDOW_SHORT = "COMMON_WINDOW_SHORT"


class ReturnInputUnit(StrEnum):
    DECIMAL = "decimal"
    PERCENT = "percent"


class LiquidityFrequency(StrEnum):
    """Redemption frequency, declared from most to least frequent."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"


class SeriesState(StrEnum):
    LIVE = "live"
    CACHED = "cached"
    FALLBACK = "fallback"
    UNAVAILABLE = "unavailable"


class ScreenOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIABLE = "unverifiable"


class SelectionReason(StrEnum):
    SELECTED_PREFERENCE_PASS = "SELECTED_PREFERENCE_PASS"
    SELECTED_RANK_PASS = "SELECTED_RANK_PASS"
    CONCENTRATION_SKIP = "CONCENTRATION_SKIP"
    CAPACITY_REACHED = "CAPACITY_REACHED"

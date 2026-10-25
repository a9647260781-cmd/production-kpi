"""Pure Decimal calculations for the synthetic demo methodology.

The functions in this module do not access a database or web framework.
Ratios are returned as unitless Decimals (``1`` means 100%). KPI fields are
returned as percent values (``90.25`` means 90.25%). Intermediate values are
never rounded. API code must serialize Decimal values without converting them
through binary floats; the agreed representation is a canonical decimal string.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence


ZERO = Decimal("0")
ONE = Decimal("1")
SIXTY = Decimal("60")
HUNDRED = Decimal("100")

MATURITY_PROVISIONAL = "PROVISIONAL"
MATURITY_AWAITING_AUDIT = "AWAITING_AUDIT"
MATURITY_FINAL = "FINAL"
MATURITY_STATES = {
    MATURITY_PROVISIONAL,
    MATURITY_AWAITING_AUDIT,
    MATURITY_FINAL,
}

STATUS_OFFICIAL = "OFFICIAL"
STATUS_RAW_ONLY = "RAW_ONLY"
STATUS_NOT_CALCULABLE = "NOT_CALCULABLE"


@dataclass(frozen=True, slots=True)
class PlanLineMetric:
    """One fixed plan position or one explicitly unplanned fact position.

    ``norm_minutes`` is measured in person-minutes. An unplanned valid fact is
    represented by ``planned_qty=0`` and still contributes to ``E_fact``.
    """

    key: str
    planned_qty: Decimal
    fact_qty: Decimal
    norm_minutes: Decimal | None


@dataclass(frozen=True, slots=True)
class ProductionInputs:
    plan_lines: Sequence[PlanLineMetric]
    h_accounted_hours: Decimal | None
    rho_target: Decimal | None
    quality_eligible_norm_hours: Decimal | None
    first_pass_good_norm_hours: Decimal | None
    maturity_state: str
    q_min: Decimal | None
    critical_quality_hold: bool
    h_rework_hours: Decimal | None = None
    completeness_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProductionMetrics:
    e_fact: Decimal | None
    e_plan: Decimal | None
    e_plan_covered: Decimal | None
    a_volume: Decimal | None
    a_plan: Decimal | None
    p_raw: Decimal | None
    q_fpy: Decimal | None
    rework_share: Decimal | None
    operational: Decimal | None
    kpi_raw: Decimal | None
    kpi_official: Decimal | None
    raw_available: bool
    official_available: bool
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OtkInputs:
    plan_lines: Sequence[PlanLineMetric]
    h_accounted_hours: Decimal | None
    rho_target: Decimal | None
    audited_correct: Decimal | None
    audited_total: Decimal | None
    sampling_valid: bool | None
    coverage_inspected: Decimal | None
    coverage_due: Decimal | None
    timely_decisions: Decimal | None
    decisions_due: Decimal | None
    maturity_state: str
    min_audit_size: Decimal | None
    completeness_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OtkMetrics:
    e_fact: Decimal | None
    e_plan: Decimal | None
    e_plan_covered: Decimal | None
    a_volume: Decimal | None
    a_plan: Decimal | None
    p_raw: Decimal | None
    q_decision: Decimal | None
    coverage: Decimal | None
    timeliness: Decimal | None
    operational: Decimal | None
    kpi_raw: Decimal | None
    kpi_official: Decimal | None
    raw_available: bool
    official_available: bool
    status: str
    reasons: tuple[str, ...]


def quantize_for_display(
    value: Decimal | None,
    places: int = 2,
) -> Decimal | None:
    """Round only a presentation value using deterministic half-up rounding."""

    if value is None:
        return None
    _require_decimal("value", value)
    if not isinstance(places, int) or isinstance(places, bool) or places < 0:
        raise ValueError("places must be a non-negative integer")
    quantum = ONE.scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def calculate_kpi(inputs: ProductionInputs) -> ProductionMetrics:
    """Calculate the proposed production KPI from already aggregated inputs."""

    _validate_maturity(inputs.maturity_state)
    _require_bool("critical_quality_hold", inputs.critical_quality_hold)
    reasons: list[str] = _completeness_reasons(inputs.completeness_errors)

    e_fact, e_plan, e_plan_covered, line_reasons = _calculate_line_totals(
        inputs.plan_lines
    )
    reasons.extend(line_reasons)

    a_volume: Decimal | None = None
    a_plan: Decimal | None = None
    if e_plan is not None:
        if e_plan == ZERO:
            reasons.append("NO_PLAN")
        else:
            if e_fact is not None:
                a_volume = e_fact / e_plan
            if e_plan_covered is not None:
                a_plan = e_plan_covered / e_plan

    p_raw = _calculate_productivity(
        e_fact=e_fact,
        h_accounted_hours=inputs.h_accounted_hours,
        rho_target=inputs.rho_target,
        reasons=reasons,
    )

    q_fpy = _calculate_quality(
        eligible=inputs.quality_eligible_norm_hours,
        good=inputs.first_pass_good_norm_hours,
        reasons=reasons,
    )

    rework_share = _calculate_rework_share(
        h_accounted_hours=inputs.h_accounted_hours,
        h_rework_hours=inputs.h_rework_hours,
    )

    operational = (
        min(a_plan, p_raw, ONE)
        if a_plan is not None and p_raw is not None
        else None
    )
    kpi_raw = (
        HUNDRED * operational * q_fpy
        if operational is not None and q_fpy is not None
        else None
    )

    official_blocked = bool(inputs.completeness_errors)
    if inputs.maturity_state != MATURITY_FINAL:
        reasons.append(f"MATURITY_{inputs.maturity_state}")
        official_blocked = True

    if inputs.q_min is None:
        reasons.append("MISSING_Q_MIN")
        official_blocked = True
    else:
        _require_non_negative_decimal("q_min", inputs.q_min)
        if inputs.q_min > ONE:
            raise ValueError("q_min must be between 0 and 1")
        if q_fpy is not None and q_fpy < inputs.q_min:
            reasons.append("QUALITY_GATE_FAILED")
            official_blocked = True

    if inputs.critical_quality_hold:
        reasons.append("CRITICAL_QUALITY_HOLD")
        official_blocked = True

    if kpi_raw is None:
        official_blocked = True

    kpi_official = None if official_blocked else kpi_raw
    reasons_tuple = _unique(reasons)
    return ProductionMetrics(
        e_fact=e_fact,
        e_plan=e_plan,
        e_plan_covered=e_plan_covered,
        a_volume=a_volume,
        a_plan=a_plan,
        p_raw=p_raw,
        q_fpy=q_fpy,
        rework_share=rework_share,
        operational=operational,
        kpi_raw=kpi_raw,
        kpi_official=kpi_official,
        raw_available=kpi_raw is not None,
        official_available=kpi_official is not None,
        status=_status(kpi_raw, kpi_official),
        reasons=reasons_tuple,
    )


def calculate_otk_kpi(inputs: OtkInputs) -> OtkMetrics:
    """Calculate the separate OTK KPI using independent audit correctness."""

    _validate_maturity(inputs.maturity_state)
    if inputs.sampling_valid is not None:
        _require_bool("sampling_valid", inputs.sampling_valid)
    reasons: list[str] = _completeness_reasons(inputs.completeness_errors)

    e_fact, e_plan, e_plan_covered, line_reasons = _calculate_line_totals(
        inputs.plan_lines
    )
    reasons.extend(line_reasons)

    a_volume: Decimal | None = None
    a_plan: Decimal | None = None
    if e_plan is not None:
        if e_plan == ZERO:
            reasons.append("NO_PLAN")
        else:
            if e_fact is not None:
                a_volume = e_fact / e_plan
            if e_plan_covered is not None:
                a_plan = e_plan_covered / e_plan

    p_raw = _calculate_productivity(
        e_fact=e_fact,
        h_accounted_hours=inputs.h_accounted_hours,
        rho_target=inputs.rho_target,
        reasons=reasons,
    )
    q_decision = _calculate_decision_quality(inputs, reasons)
    coverage = _calculate_optional_ratio(
        "coverage",
        inputs.coverage_inspected,
        inputs.coverage_due,
    )
    timeliness = _calculate_optional_ratio(
        "timeliness",
        inputs.timely_decisions,
        inputs.decisions_due,
    )

    operational = (
        min(a_plan, p_raw, ONE)
        if a_plan is not None and p_raw is not None
        else None
    )
    kpi_raw = (
        HUNDRED * operational * q_decision
        if operational is not None and q_decision is not None
        else None
    )

    official_blocked = bool(inputs.completeness_errors)
    if inputs.maturity_state != MATURITY_FINAL:
        reasons.append(f"MATURITY_{inputs.maturity_state}")
        official_blocked = True
    if kpi_raw is None:
        official_blocked = True

    kpi_official = None if official_blocked else kpi_raw
    reasons_tuple = _unique(reasons)
    return OtkMetrics(
        e_fact=e_fact,
        e_plan=e_plan,
        e_plan_covered=e_plan_covered,
        a_volume=a_volume,
        a_plan=a_plan,
        p_raw=p_raw,
        q_decision=q_decision,
        coverage=coverage,
        timeliness=timeliness,
        operational=operational,
        kpi_raw=kpi_raw,
        kpi_official=kpi_official,
        raw_available=kpi_raw is not None,
        official_available=kpi_official is not None,
        status=_status(kpi_raw, kpi_official),
        reasons=reasons_tuple,
    )


def _calculate_line_totals(
    lines: Sequence[PlanLineMetric],
) -> tuple[Decimal | None, Decimal | None, Decimal | None, list[str]]:
    e_fact = ZERO
    e_plan = ZERO
    e_plan_covered = ZERO
    reasons: list[str] = []
    seen: set[str] = set()

    for line in lines:
        if not line.key:
            raise ValueError("plan line key must not be empty")
        if line.key in seen:
            raise ValueError(f"duplicate plan line key: {line.key}")
        seen.add(line.key)

        _require_non_negative_decimal(
            f"plan_lines[{line.key}].planned_qty", line.planned_qty
        )
        _require_non_negative_decimal(
            f"plan_lines[{line.key}].fact_qty", line.fact_qty
        )
        material = line.planned_qty != ZERO or line.fact_qty != ZERO
        if line.norm_minutes is None:
            if material:
                reasons.append(f"MISSING_NORM:{line.key}")
            continue
        _require_decimal(f"plan_lines[{line.key}].norm_minutes", line.norm_minutes)
        if line.norm_minutes <= ZERO:
            if material:
                reasons.append(f"INVALID_NORM:{line.key}")
            continue

        norm_hours = line.norm_minutes / SIXTY
        e_fact += line.fact_qty * norm_hours
        e_plan += line.planned_qty * norm_hours
        e_plan_covered += min(line.fact_qty, line.planned_qty) * norm_hours

    if reasons:
        return None, None, None, reasons
    return e_fact, e_plan, e_plan_covered, reasons


def _calculate_productivity(
    *,
    e_fact: Decimal | None,
    h_accounted_hours: Decimal | None,
    rho_target: Decimal | None,
    reasons: list[str],
) -> Decimal | None:
    if h_accounted_hours is None:
        reasons.append("MISSING_ACCOUNTED_HOURS")
        return None
    _require_non_negative_decimal("h_accounted_hours", h_accounted_hours)
    if rho_target is None:
        reasons.append("MISSING_RHO_TARGET")
        return None
    _require_non_negative_decimal("rho_target", rho_target)
    if rho_target == ZERO:
        reasons.append("ZERO_RHO_TARGET")
        return None
    if h_accounted_hours == ZERO:
        reasons.append(
            "ZERO_ACCOUNTED_HOURS"
            if e_fact is not None and e_fact > ZERO
            else "NO_LABOR_BASE"
        )
        return None
    if e_fact is None:
        return None
    return e_fact / (h_accounted_hours * rho_target)


def _calculate_quality(
    *,
    eligible: Decimal | None,
    good: Decimal | None,
    reasons: list[str],
) -> Decimal | None:
    if eligible is None:
        reasons.append("MISSING_QUALITY_ELIGIBLE")
        return None
    _require_non_negative_decimal("quality_eligible_norm_hours", eligible)
    if eligible == ZERO:
        reasons.append("NO_QUALITY_ELIGIBLE")
        return None
    if good is None:
        reasons.append("MISSING_FIRST_PASS_GOOD")
        return None
    _require_non_negative_decimal("first_pass_good_norm_hours", good)
    if good > eligible:
        raise ValueError("first_pass_good_norm_hours cannot exceed eligible hours")
    return good / eligible


def _calculate_rework_share(
    *,
    h_accounted_hours: Decimal | None,
    h_rework_hours: Decimal | None,
) -> Decimal | None:
    if h_rework_hours is None:
        return None
    _require_non_negative_decimal("h_rework_hours", h_rework_hours)
    if h_accounted_hours is None:
        return None
    _require_non_negative_decimal("h_accounted_hours", h_accounted_hours)
    if h_rework_hours > h_accounted_hours:
        raise ValueError("h_rework_hours cannot exceed h_accounted_hours")
    if h_accounted_hours == ZERO:
        return None
    return h_rework_hours / h_accounted_hours


def _calculate_decision_quality(
    inputs: OtkInputs,
    reasons: list[str],
) -> Decimal | None:
    if inputs.sampling_valid is False:
        reasons.append("BIASED_AUDIT_SAMPLE")
        return None
    if inputs.sampling_valid is None:
        reasons.append("MISSING_AUDIT_PROTOCOL")
        return None
    if inputs.audited_total is None or inputs.audited_correct is None:
        reasons.append("NO_AUDIT_DATA")
        return None
    _require_non_negative_decimal("audited_total", inputs.audited_total)
    _require_non_negative_decimal("audited_correct", inputs.audited_correct)
    if inputs.audited_correct > inputs.audited_total:
        raise ValueError("audited_correct cannot exceed audited_total")
    if inputs.audited_total == ZERO:
        reasons.append("NO_AUDIT")
        return None
    if inputs.min_audit_size is None:
        reasons.append("MISSING_MIN_AUDIT_SIZE")
        return None
    _require_non_negative_decimal("min_audit_size", inputs.min_audit_size)
    if inputs.audited_total < inputs.min_audit_size:
        reasons.append("INSUFFICIENT_AUDIT_SAMPLE")
        return None
    return inputs.audited_correct / inputs.audited_total


def _calculate_optional_ratio(
    name: str,
    numerator: Decimal | None,
    denominator: Decimal | None,
) -> Decimal | None:
    if numerator is None or denominator is None:
        return None
    _require_non_negative_decimal(f"{name}_numerator", numerator)
    _require_non_negative_decimal(f"{name}_denominator", denominator)
    if numerator > denominator:
        raise ValueError(f"{name} numerator cannot exceed denominator")
    if denominator == ZERO:
        return None
    return numerator / denominator


def _completeness_reasons(errors: Iterable[str]) -> list[str]:
    reasons: list[str] = []
    for error in errors:
        if not error:
            raise ValueError("completeness error code must not be empty")
        reasons.append(f"INCOMPLETE_DATA:{error}")
    return reasons


def _validate_maturity(value: str) -> None:
    if value not in MATURITY_STATES:
        raise ValueError(f"unknown maturity_state: {value}")


def _require_decimal(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


def _require_non_negative_decimal(name: str, value: Decimal) -> None:
    _require_decimal(name, value)
    if value < ZERO:
        raise ValueError(f"{name} must not be negative")


def _require_bool(name: str, value: bool) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be bool")


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _status(
    kpi_raw: Decimal | None,
    kpi_official: Decimal | None,
) -> str:
    if kpi_official is not None:
        return STATUS_OFFICIAL
    if kpi_raw is not None:
        return STATUS_RAW_ONLY
    return STATUS_NOT_CALCULABLE

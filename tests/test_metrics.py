from decimal import Decimal

import pytest

from app.calculations import (
    MATURITY_AWAITING_AUDIT,
    MATURITY_FINAL,
    MATURITY_PROVISIONAL,
    OtkInputs,
    PlanLineMetric,
    ProductionInputs,
    calculate_kpi,
    calculate_otk_kpi,
    quantize_for_display,
)


def d(value: str | int) -> Decimal:
    return Decimal(str(value))


def line(
    key: str,
    planned: str | int,
    fact: str | int,
    minutes: str | int | None,
) -> PlanLineMetric:
    return PlanLineMetric(
        key=key,
        planned_qty=d(planned),
        fact_qty=d(fact),
        norm_minutes=None if minutes is None else d(minutes),
    )


def production_inputs(
    lines: tuple[PlanLineMetric, ...],
    *,
    hours: Decimal | None,
    eligible: Decimal | None,
    good: Decimal | None,
    rho: Decimal | None = Decimal("1"),
    maturity: str = MATURITY_FINAL,
    q_min: Decimal | None = Decimal("0"),
    hold: bool = False,
    rework: Decimal | None = None,
    errors: tuple[str, ...] = (),
) -> ProductionInputs:
    return ProductionInputs(
        plan_lines=lines,
        h_accounted_hours=hours,
        rho_target=rho,
        quality_eligible_norm_hours=eligible,
        first_pass_good_norm_hours=good,
        maturity_state=maturity,
        q_min=q_min,
        critical_quality_hold=hold,
        h_rework_hours=rework,
        completeness_errors=errors,
    )


def otk_inputs(
    *,
    audited_correct: Decimal | None,
    audited_total: Decimal | None,
    sampling_valid: bool | None,
    maturity: str = MATURITY_FINAL,
    min_audit_size: Decimal | None = Decimal("1"),
) -> OtkInputs:
    return OtkInputs(
        plan_lines=(line("DEMO:OTK", 50, 45, 60),),
        h_accounted_hours=d(40),
        rho_target=d(1),
        audited_correct=audited_correct,
        audited_total=audited_total,
        sampling_valid=sampling_valid,
        coverage_inspected=d(50),
        coverage_due=d(50),
        timely_decisions=d(49),
        decisions_due=d(50),
        maturity_state=maturity,
        min_audit_size=min_audit_size,
    )


def test_mixed_positions_cap_surplus_and_give_90_25_percent() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (
                line("DEMO:A", 100, 90, 6),
                line("DEMO:B", 50, 55, 12),
            ),
            hours=d(20),
            eligible=d(20),
            good=d(19),
            q_min=d("0.90"),
        )
    )

    assert metrics.e_fact == d(20)
    assert metrics.e_plan == d(20)
    assert metrics.e_plan_covered == d(19)
    assert metrics.a_volume == d(1)
    assert metrics.a_plan == d("0.95")
    assert metrics.p_raw == d(1)
    assert metrics.q_fpy == d("0.95")
    assert metrics.operational == d("0.95")
    assert metrics.kpi_raw == d("90.25")
    assert metrics.kpi_official == d("90.25")
    assert metrics.official_available is True


def test_fast_work_does_not_hide_plan_shortfall_87_3_percent() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:PLAN", 20, 18, 60),),
            hours=d(15),
            eligible=d(18),
            good=d("17.46"),
            q_min=d("0.90"),
        )
    )

    assert metrics.a_plan == d("0.9")
    assert metrics.p_raw == d("1.2")
    assert metrics.q_fpy == d("0.97")
    assert metrics.operational == d("0.9")
    assert metrics.kpi_raw == d("87.300")
    assert quantize_for_display(metrics.kpi_raw) == d("87.30")


def test_overproduction_does_not_hide_low_productivity() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:PLAN", 20, 24, 60),),
            hours=d(30),
            eligible=d(24),
            good=d(24),
        )
    )

    assert metrics.a_volume == d("1.2")
    assert metrics.a_plan == d(1)
    assert metrics.p_raw == d("0.8")
    assert metrics.kpi_raw == d(80)


def test_rework_consumes_hours_without_earning_second_output() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:PRIMARY", 100, 100, 6),),
            hours=d(12),
            eligible=d(10),
            good=d(9),
            rework=d(2),
        )
    )

    assert metrics.e_fact == d(10)
    assert quantize_for_display(metrics.p_raw * d(100)) == d("83.33")
    assert quantize_for_display(metrics.rework_share * d(100)) == d("16.67")


def test_otk_independent_audit_gives_86_4_percent() -> None:
    metrics = calculate_otk_kpi(
        otk_inputs(
            audited_correct=d(96),
            audited_total=d(100),
            sampling_valid=True,
            min_audit_size=d(20),
        )
    )

    assert metrics.a_plan == d("0.9")
    assert metrics.p_raw == d("1.125")
    assert metrics.q_decision == d("0.96")
    assert metrics.coverage == d(1)
    assert metrics.timeliness == d("0.98")
    assert metrics.kpi_raw == d("86.400")
    assert quantize_for_display(metrics.kpi_raw) == d("86.40")
    assert metrics.kpi_official == metrics.kpi_raw


def test_no_output_has_zero_plan_and_productivity_but_no_quality_or_kpi() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:EMPTY", 10, 0, 60),),
            hours=d(8),
            eligible=d(0),
            good=d(0),
        )
    )

    assert metrics.a_volume == d(0)
    assert metrics.a_plan == d(0)
    assert metrics.p_raw == d(0)
    assert metrics.q_fpy is None
    assert metrics.kpi_raw is None
    assert metrics.kpi_official is None
    assert "NO_QUALITY_ELIGIBLE" in metrics.reasons


def test_no_audit_never_means_perfect_otk_quality() -> None:
    metrics = calculate_otk_kpi(
        otk_inputs(
            audited_correct=d(0),
            audited_total=d(0),
            sampling_valid=True,
        )
    )

    assert metrics.q_decision is None
    assert metrics.kpi_raw is None
    assert metrics.kpi_official is None
    assert "NO_AUDIT" in metrics.reasons


def test_biased_otk_sample_returns_null_quality_and_composite() -> None:
    metrics = calculate_otk_kpi(
        otk_inputs(
            audited_correct=d(26),
            audited_total=d(28),
            sampling_valid=False,
        )
    )

    assert metrics.q_decision is None
    assert metrics.kpi_raw is None
    assert metrics.kpi_official is None
    assert "BIASED_AUDIT_SAMPLE" in metrics.reasons


def test_insufficient_audit_sample_returns_null() -> None:
    metrics = calculate_otk_kpi(
        otk_inputs(
            audited_correct=d(9),
            audited_total=d(10),
            sampling_valid=True,
            min_audit_size=d(20),
        )
    )

    assert metrics.q_decision is None
    assert "INSUFFICIENT_AUDIT_SAMPLE" in metrics.reasons


def test_missing_norm_blocks_norm_hour_metrics_with_reason() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:NO_NORM", 10, 8, None),),
            hours=d(8),
            eligible=d(8),
            good=d(8),
        )
    )

    assert metrics.e_fact is None
    assert metrics.a_volume is None
    assert metrics.p_raw is None
    assert metrics.kpi_raw is None
    assert "MISSING_NORM:DEMO:NO_NORM" in metrics.reasons


def test_unplanned_fact_counts_in_volume_but_not_plan_coverage() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (
                line("DEMO:PLANNED", 10, 10, 60),
                line("DEMO:UNPLANNED", 0, 5, 60),
            ),
            hours=d(15),
            eligible=d(15),
            good=d(15),
        )
    )

    assert metrics.e_fact == d(15)
    assert metrics.e_plan == d(10)
    assert metrics.e_plan_covered == d(10)
    assert metrics.a_volume == d("1.5")
    assert metrics.a_plan == d(1)


def test_no_plan_keeps_productivity_but_blocks_composite() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:UNPLANNED", 0, 5, 60),),
            hours=d(5),
            eligible=d(5),
            good=d(5),
        )
    )

    assert metrics.e_fact == d(5)
    assert metrics.a_volume is None
    assert metrics.a_plan is None
    assert metrics.p_raw == d(1)
    assert metrics.kpi_raw is None
    assert "NO_PLAN" in metrics.reasons


def test_missing_hours_is_null_not_zero() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:PLAN", 10, 10, 60),),
            hours=None,
            eligible=d(10),
            good=d(10),
        )
    )

    assert metrics.p_raw is None
    assert metrics.kpi_raw is None
    assert "MISSING_ACCOUNTED_HOURS" in metrics.reasons


def test_aggregation_uses_ratio_of_sums_not_average_of_percentages() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (
                line("DEMO:COHORT_1", 10, 10, 60),
                line("DEMO:COHORT_2", 90, 90, 60),
            ),
            hours=d(100),
            eligible=d(100),
            good=d(99),
        )
    )

    assert metrics.q_fpy == d("0.99")
    assert metrics.kpi_raw == d(99)


def test_aggregation_preserves_each_fixed_plan_line_cap() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (
                line("DEMO:SHIFT_1", 10, 15, 60),
                line("DEMO:SHIFT_2", 10, 5, 60),
            ),
            hours=d(20),
            eligible=d(20),
            good=d(20),
        )
    )

    assert metrics.a_volume == d(1)
    assert metrics.e_plan_covered == d(15)
    assert metrics.a_plan == d("0.75")
    assert metrics.kpi_raw == d(75)


@pytest.mark.parametrize(
    ("maturity", "reason"),
    [
        (MATURITY_PROVISIONAL, "MATURITY_PROVISIONAL"),
        (MATURITY_AWAITING_AUDIT, "MATURITY_AWAITING_AUDIT"),
    ],
)
def test_immature_quality_exposes_raw_but_not_official(
    maturity: str,
    reason: str,
) -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:PLAN", 10, 10, 60),),
            hours=d(10),
            eligible=d(10),
            good=d(10),
            maturity=maturity,
        )
    )

    assert metrics.kpi_raw == d(100)
    assert metrics.kpi_official is None
    assert metrics.raw_available is True
    assert metrics.official_available is False
    assert reason in metrics.reasons


def test_quality_gate_and_hold_block_official_but_keep_raw() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:PLAN", 10, 10, 60),),
            hours=d(10),
            eligible=d(10),
            good=d(9),
            q_min=d("0.95"),
            hold=True,
        )
    )

    assert metrics.kpi_raw == d(90)
    assert metrics.kpi_official is None
    assert "QUALITY_GATE_FAILED" in metrics.reasons
    assert "CRITICAL_QUALITY_HOLD" in metrics.reasons


def test_completeness_error_blocks_official_only() -> None:
    metrics = calculate_kpi(
        production_inputs(
            (line("DEMO:PLAN", 10, 10, 60),),
            hours=d(10),
            eligible=d(10),
            good=d(10),
            errors=("UNRESOLVED_EVENT",),
        )
    )

    assert metrics.kpi_raw == d(100)
    assert metrics.kpi_official is None
    assert "INCOMPLETE_DATA:UNRESOLVED_EVENT" in metrics.reasons


def test_decimal_contract_rejects_binary_float() -> None:
    with pytest.raises(TypeError, match="must be Decimal"):
        calculate_kpi(
            ProductionInputs(
                plan_lines=(
                    PlanLineMetric(
                        key="DEMO:FLOAT",
                        planned_qty=10.0,  # type: ignore[arg-type]
                        fact_qty=d(10),
                        norm_minutes=d(60),
                    ),
                ),
                h_accounted_hours=d(10),
                rho_target=d(1),
                quality_eligible_norm_hours=d(10),
                first_pass_good_norm_hours=d(10),
                maturity_state=MATURITY_FINAL,
                q_min=d(0),
                critical_quality_hold=False,
            )
        )


def test_duplicate_plan_keys_are_rejected_before_capping() -> None:
    with pytest.raises(ValueError, match="duplicate plan line key"):
        calculate_kpi(
            production_inputs(
                (
                    line("DEMO:SAME", 10, 8, 60),
                    line("DEMO:SAME", 10, 2, 60),
                ),
                hours=d(10),
                eligible=d(10),
                good=d(10),
            )
        )


def test_rounding_is_half_up_and_never_changes_raw_value() -> None:
    raw = d("83.325")

    assert quantize_for_display(raw, 2) == d("83.33")
    assert raw == d("83.325")

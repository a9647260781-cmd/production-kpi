from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    OperationEvent,
    PlanLine,
    ProductionRow,
    ProductionPlanVersion,
    QualityAudit,
    QualityDecision,
    RouteStep,
    ShiftAssignment,
    StandardSetVersion,
    StandardValue,
    TimeEntry,
    TrackedEntity,
    User,
    WorkSession,
    utcnow,
)
from app.services import calculate_row_metrics, calculate_shift


def _shift_id(db: Session) -> str:
    plan = db.scalar(
        select(ProductionPlanVersion)
        .where(ProductionPlanVersion.status == "APPROVED")
        .order_by(ProductionPlanVersion.version.desc())
    )
    assert plan is not None
    return plan.shift_id


def _decimal(metrics: dict, *path: str) -> Decimal:
    value = metrics
    for key in path:
        value = value[key]
    assert isinstance(value, str)
    return Decimal(value)


def test_new_plan_version_uses_stable_business_keys_for_existing_facts(
    seeded_db: Session,
) -> None:
    shift_id = _shift_id(seeded_db)
    before = calculate_shift(seeded_db, shift_id)
    old_plan = seeded_db.scalar(
        select(ProductionPlanVersion).where(
            ProductionPlanVersion.shift_id == shift_id,
            ProductionPlanVersion.status == "APPROVED",
        )
    )
    assert old_plan is not None
    old_lines = list(
        seeded_db.scalars(
            select(PlanLine).where(PlanLine.plan_version_id == old_plan.id)
        )
    )
    new_plan = ProductionPlanVersion(
        shift_id=shift_id,
        standard_version_id=old_plan.standard_version_id,
        version=old_plan.version + 1,
        status="APPROVED",
        supersedes_id=old_plan.id,
        approved_at=utcnow(),
        approved_by_id=old_plan.approved_by_id,
        reason="DEMO stable business key test",
    )
    seeded_db.add(new_plan)
    seeded_db.flush()
    for old in old_lines:
        seeded_db.add(
            PlanLine(
                plan_version_id=new_plan.id,
                key=old.key,
                model_id=old.model_id,
                route_step_id=old.route_step_id,
                row_id=old.row_id,
                planned_qty=old.planned_qty,
                norm_minutes=old.norm_minutes,
            )
        )
    seeded_db.commit()

    after = calculate_shift(seeded_db, shift_id)

    assert after["trace"]["plan_version"] == old_plan.version + 1
    assert after["production"]["e_fact"] == before["production"]["e_fact"]
    assert after["production"]["a_plan"] == before["production"]["a_plan"]


def test_accepted_correction_removes_original_primary_credit(
    seeded_db: Session,
) -> None:
    shift_id = _shift_id(seeded_db)
    before = calculate_shift(seeded_db, shift_id)
    original = seeded_db.scalar(
        select(OperationEvent)
        .join(RouteStep, RouteStep.id == OperationEvent.route_step_id)
        .where(
            OperationEvent.shift_id == shift_id,
            OperationEvent.attempt_type == "PRIMARY",
            RouteStep.code == "DEMO-SOLDER",
        )
        .order_by(OperationEvent.server_received_at)
    )
    assert original is not None
    seeded_db.add(
        OperationEvent(
            id=str(uuid4()),
            payload_hash="a" * 64,
            shift_id=original.shift_id,
            work_session_id=original.work_session_id,
            entity_id=original.entity_id,
            route_step_id=original.route_step_id,
            plan_line_id=original.plan_line_id,
            user_id=original.user_id,
            attempt_no=original.attempt_no,
            attempt_type="PRIMARY",
            event_type="CORRECTION",
            outcome="CANCELLED",
            status="ACCEPTED",
            code="DEMO_CORRECTION",
            correction_of_id=original.id,
            reason="DEMO calculation correction",
        )
    )
    seeded_db.commit()

    after = calculate_shift(seeded_db, shift_id)

    assert _decimal(before, "production", "e_fact") - _decimal(
        after, "production", "e_fact"
    ) == Decimal("0.1")


def test_unplanned_primary_fact_increases_volume_not_plan_coverage(
    seeded_db: Session,
) -> None:
    shift_id = _shift_id(seeded_db)
    before = calculate_shift(seeded_db, shift_id)
    template = seeded_db.scalar(
        select(TrackedEntity).where(TrackedEntity.qr_code == "DEMO-WIP-001")
    )
    session = seeded_db.scalar(
        select(WorkSession)
        .join(User, User.id == WorkSession.user_id)
        .where(User.username == "solder")
    )
    solder_step = seeded_db.scalar(
        select(RouteStep).where(RouteStep.code == "DEMO-SOLDER")
    )
    assert template is not None and session is not None and solder_step is not None
    entity = TrackedEntity(
        id=str(uuid4()),
        qr_code="DEMO-SERVICE-UNPLANNED",
        entity_type="WIP",
        model_id=template.model_id,
        route_version_id=template.route_version_id,
        status="IN_PROGRESS",
    )
    seeded_db.add(entity)
    seeded_db.flush()
    seeded_db.add(
        OperationEvent(
            id=str(uuid4()),
            payload_hash="b" * 64,
            shift_id=shift_id,
            work_session_id=session.id,
            entity_id=entity.id,
            route_step_id=solder_step.id,
            plan_line_id=None,
            user_id=session.user_id,
            attempt_no=1,
            attempt_type="PRIMARY",
            event_type="COMPLETE",
            outcome="COMPLETED",
            status="ACCEPTED",
            code="EVENT_ACCEPTED",
        )
    )
    seeded_db.commit()

    after = calculate_shift(seeded_db, shift_id)

    assert _decimal(after, "production", "e_fact") - _decimal(
        before, "production", "e_fact"
    ) == Decimal("0.1")
    assert after["production"]["e_plan_covered"] == before["production"][
        "e_plan_covered"
    ]
    assert _decimal(after, "production", "a_volume") > _decimal(
        before, "production", "a_volume"
    )


def test_incomplete_primary_quality_cohort_blocks_official_kpi(
    seeded_db: Session,
) -> None:
    decision = seeded_db.scalar(
        select(QualityDecision).where(QualityDecision.decision == "ACCEPT")
    )
    assert decision is not None
    seeded_db.execute(
        delete(QualityAudit).where(QualityAudit.decision_id == decision.id)
    )
    seeded_db.delete(decision)
    seeded_db.commit()

    metrics = calculate_shift(seeded_db, _shift_id(seeded_db))

    assert metrics["production"]["kpi_raw"] is not None
    assert metrics["production"]["kpi_official"] is None
    assert (
        "INCOMPLETE_DATA:INCOMPLETE_QUALITY_COHORT"
        in metrics["production"]["reasons"]
    )
    assert metrics["otk"]["coverage"] == "0.6666666666666666666666666667"
    assert metrics["otk"]["kpi_official"] is None


def test_superseded_time_entry_is_not_double_counted(
    seeded_db: Session,
) -> None:
    shift_id = _shift_id(seeded_db)
    before = calculate_shift(seeded_db, shift_id)
    original = seeded_db.scalar(
        select(TimeEntry)
        .join(ShiftAssignment, ShiftAssignment.id == TimeEntry.assignment_id)
        .join(User, User.employee_id == ShiftAssignment.employee_id)
        .where(User.username == "assembly1", TimeEntry.category == "PRIMARY")
    )
    assert original is not None
    seeded_db.add(
        TimeEntry(
            assignment_id=original.assignment_id,
            category=original.category,
            hours=Decimal("7"),
            source="DEMO_CORRECTION",
            approval_status="APPROVED",
            version=original.version + 1,
            supersedes_id=original.id,
            reason="DEMO corrected ledger",
        )
    )
    seeded_db.commit()

    after = calculate_shift(seeded_db, shift_id)

    assert Decimal(before["inputs"]["h_accounted_hours"]) - Decimal(
        after["inputs"]["h_accounted_hours"]
    ) == Decimal("1")


def test_qc_rework_hours_do_not_leak_into_production_rework_share(
    seeded_db: Session,
) -> None:
    shift_id = _shift_id(seeded_db)
    before = calculate_shift(seeded_db, shift_id)
    qc_assignment = seeded_db.scalar(
        select(ShiftAssignment)
        .join(RouteStep, RouteStep.id == ShiftAssignment.route_step_id)
        .where(RouteStep.code == "DEMO-QC")
    )
    assert qc_assignment is not None
    seeded_db.add(
        TimeEntry(
            assignment_id=qc_assignment.id,
            category="REWORK",
            hours=Decimal("1"),
            source="DEMO_QC_REWORK",
            approval_status="APPROVED",
            version=1,
        )
    )
    seeded_db.commit()

    after = calculate_shift(seeded_db, shift_id)

    assert after["inputs"]["h_rework_hours"] == before["inputs"][
        "h_rework_hours"
    ]
    assert after["inputs"]["h_accounted_hours"] == before["inputs"][
        "h_accounted_hours"
    ]


def test_calculation_trace_uses_standard_version_frozen_on_plan(
    seeded_db: Session,
) -> None:
    shift_id = _shift_id(seeded_db)
    plan = seeded_db.scalar(
        select(ProductionPlanVersion).where(
            ProductionPlanVersion.shift_id == shift_id,
            ProductionPlanVersion.status == "APPROVED",
        )
    )
    assert plan is not None
    frozen_standard_id = plan.standard_version_id
    frozen = seeded_db.get(StandardSetVersion, frozen_standard_id)
    assert frozen is not None
    newer = StandardSetVersion(
        model_id=frozen.model_id,
        version=frozen.version + 1,
        status="APPROVED",
        effective_from=frozen.effective_from + timedelta(days=1),
        approved_at=utcnow(),
        approved_by_id=frozen.approved_by_id,
        supersedes_id=frozen.id,
    )
    seeded_db.add(newer)
    seeded_db.flush()
    for value in list(
        seeded_db.scalars(
            select(StandardValue).where(StandardValue.standard_set_id == frozen.id)
        )
    ):
        seeded_db.add(
            StandardValue(
                standard_set_id=newer.id,
                route_step_id=value.route_step_id,
                norm_minutes=Decimal("99"),
            )
        )
    seeded_db.commit()

    metrics = calculate_shift(seeded_db, shift_id)

    assert metrics["trace"]["standard_version_id"] == frozen_standard_id
    assert metrics["trace"]["standard_version"] == frozen.version
    assert metrics["otk"]["timeliness"] is None


def test_row_metrics_cover_all_five_rows_without_fake_production_quality(
    seeded_db: Session,
) -> None:
    shift_id = _shift_id(seeded_db)
    rows = {
        row.code: calculate_row_metrics(seeded_db, shift_id, row.id)
        for row in seeded_db.scalars(select(ProductionRow).order_by(ProductionRow.sort_order))
    }

    assert set(rows) == {
        "DEMO-ASM-01", "DEMO-ASM-02", "DEMO-ASM-03", "DEMO-SOLDER-01", "DEMO-QC-01",
    }
    assert rows["DEMO-ASM-01"]["a_plan"] == "0.5"
    assert rows["DEMO-ASM-01"]["h_accounted_hours"] == "16"
    assert rows["DEMO-ASM-01"]["p"] == "0.0125"
    assert rows["DEMO-ASM-02"]["h_accounted_hours"] == "8"
    assert rows["DEMO-SOLDER-01"]["a_plan"] == "0.5"
    assert rows["DEMO-SOLDER-01"]["p"] == "0.0375"

    for code in ["DEMO-ASM-01", "DEMO-ASM-02", "DEMO-ASM-03", "DEMO-SOLDER-01"]:
        assert rows[code]["q"] is None
        assert rows[code]["kpi_raw"] is None
        assert rows[code]["kpi_official"] is None
        assert "ROW_QUALITY_NOT_ATTRIBUTABLE" in rows[code]["reason_flags"]

    qc = rows["DEMO-QC-01"]
    assert qc["a_plan"] == "0.5"
    assert qc["p"] == "0.025"
    assert qc["h_accounted_hours"] == "8"
    assert qc["q"] == "1"
    assert qc["kpi_raw"] == "2.5"
    assert qc["kpi_official"] == "2.5"


def test_qc_row_metrics_require_independent_audit(seeded_db: Session) -> None:
    shift_id = _shift_id(seeded_db)
    qc_row = seeded_db.scalar(select(ProductionRow).where(ProductionRow.category == "QC"))
    assert qc_row is not None
    seeded_db.execute(delete(QualityAudit))
    seeded_db.commit()

    metrics = calculate_row_metrics(seeded_db, shift_id, qc_row.id)

    assert metrics["q"] is None
    assert metrics["kpi_raw"] is None
    assert metrics["kpi_official"] is None
    assert "NO_AUDIT" in metrics["reason_flags"]

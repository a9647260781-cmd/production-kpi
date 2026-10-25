from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.calculations import (
    OtkInputs,
    PlanLineMetric,
    ProductionInputs,
    calculate_kpi,
    calculate_otk_kpi,
)
from app.errors import APIError
from app.models import (
    AuditEvent,
    OperationEvent,
    PlanLine,
    ProductionRow,
    ProductionPlanVersion,
    QualityAudit,
    QualityDecision,
    RouteStep,
    Shift,
    ShiftAssignment,
    StandardSetVersion,
    StandardValue,
    TimeEntry,
    TrackedEntity,
    WorkSession,
)


def decimal_string(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    return value


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(json_ready(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def record_audit(
    db: Session,
    *,
    actor_user_id: str | None,
    action: str,
    object_type: str,
    object_id: str,
    trace_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        before=json_ready(before),
        after=json_ready(after),
        reason=reason,
        trace_id=trace_id,
    )
    db.add(event)
    return event


def latest_approved_plan(db: Session, shift_id: str) -> ProductionPlanVersion:
    plan = db.scalar(
        select(ProductionPlanVersion)
        .where(ProductionPlanVersion.shift_id == shift_id, ProductionPlanVersion.status == "APPROVED")
        .order_by(ProductionPlanVersion.version.desc())
    )
    if plan is None:
        raise APIError(409, "APPROVED_PLAN_MISSING", "Для смены нет утверждённой версии плана")
    return plan


def latest_approved_standard(db: Session, model_id: str) -> StandardSetVersion:
    standard = db.scalar(
        select(StandardSetVersion)
        .where(StandardSetVersion.model_id == model_id, StandardSetVersion.status == "APPROVED")
        .order_by(StandardSetVersion.version.desc())
    )
    if standard is None:
        raise APIError(409, "APPROVED_STANDARD_MISSING", "Нет утверждённой версии норм")
    return standard


def _hours_for_categories(db: Session, shift_id: str, categories: Iterable[str], row_categories: Iterable[str] | None = None) -> Decimal:
    from app.models import ProductionRow

    query = (
        select(func.coalesce(func.sum(TimeEntry.hours), 0))
        .join(ShiftAssignment, ShiftAssignment.id == TimeEntry.assignment_id)
    )
    if row_categories is not None:
        query = query.join(ProductionRow, ProductionRow.id == ShiftAssignment.row_id).where(ProductionRow.category.in_(tuple(row_categories)))
    correction = aliased(TimeEntry)
    value = db.scalar(
        query.where(
            ShiftAssignment.shift_id == shift_id,
            TimeEntry.approval_status == "APPROVED",
            TimeEntry.category.in_(tuple(categories)),
            ~select(correction.id).where(correction.supersedes_id == TimeEntry.id).exists(),
        )
    )
    return Decimal(value or 0)


def _hours_for_step_category(db: Session, shift_id: str, row_category: str) -> Decimal:
    from app.models import ProductionRow

    correction = aliased(TimeEntry)
    value = db.scalar(
        select(func.coalesce(func.sum(TimeEntry.hours), 0))
        .join(ShiftAssignment, ShiftAssignment.id == TimeEntry.assignment_id)
        .join(ProductionRow, ProductionRow.id == ShiftAssignment.row_id)
        .where(
            ShiftAssignment.shift_id == shift_id,
            ProductionRow.category == row_category,
            TimeEntry.approval_status == "APPROVED",
            TimeEntry.category != "UNAVAILABLE",
            ~select(correction.id).where(correction.supersedes_id == TimeEntry.id).exists(),
        )
    )
    return Decimal(value or 0)


def _fact_count(db: Session, line: PlanLine, shift_id: str) -> Decimal:
    correction = aliased(OperationEvent)
    query = (
        select(func.count()).select_from(OperationEvent)
        .join(PlanLine, PlanLine.id == OperationEvent.plan_line_id)
        .join(WorkSession, WorkSession.id == OperationEvent.work_session_id)
        .where(
            OperationEvent.shift_id == shift_id,
            PlanLine.key == line.key,
            PlanLine.model_id == line.model_id,
            PlanLine.route_step_id == line.route_step_id,
            OperationEvent.status == "ACCEPTED",
            OperationEvent.event_type == "COMPLETE",
            OperationEvent.attempt_type == "PRIMARY",
            OperationEvent.correction_of_id.is_(None),
            ~select(correction.id).where(correction.correction_of_id == OperationEvent.id, correction.status == "ACCEPTED").exists(),
        )
    )
    if line.row_id is not None:
        query = query.where(WorkSession.row_id == line.row_id)
    count = db.scalar(query)
    return Decimal(count or 0)


def _line_inputs(db: Session, lines: list[PlanLine], shift_id: str) -> list[PlanLineMetric]:
    return [
        PlanLineMetric(
            key=line.key,
            planned_qty=Decimal(line.planned_qty),
            fact_qty=_fact_count(db, line, shift_id),
            norm_minutes=Decimal(line.norm_minutes) if line.norm_minutes is not None else None,
        )
        for line in lines
    ]


def _unplanned_inputs(
    db: Session,
    *,
    shift_id: str,
    current_lines: list[PlanLine],
    standard: StandardSetVersion,
    qc: bool,
) -> list[PlanLineMetric]:
    standard_norms = {
        value.route_step_id: Decimal(value.norm_minutes)
        for value in db.scalars(select(StandardValue).where(StandardValue.standard_set_id == standard.id))
    }
    groups: dict[str, tuple[Decimal, Decimal | None]] = {}
    correction = aliased(OperationEvent)
    events = db.scalars(
        select(OperationEvent).where(
            OperationEvent.shift_id == shift_id,
            OperationEvent.status == "ACCEPTED",
            OperationEvent.event_type == "COMPLETE",
            OperationEvent.attempt_type == "PRIMARY",
            OperationEvent.correction_of_id.is_(None),
            ~select(correction.id).where(
                correction.correction_of_id == OperationEvent.id,
                correction.status == "ACCEPTED",
            ).exists(),
        )
    )
    for event in events:
        old_line = db.get(PlanLine, event.plan_line_id) if event.plan_line_id else None
        step = db.get(RouteStep, event.route_step_id)
        if step is None or (("QC" in step.code) != qc):
            continue
        session = db.get(WorkSession, event.work_session_id)
        row_id = session.row_id if session else "UNKNOWN"
        entity = db.get(TrackedEntity, event.entity_id)
        model_id = old_line.model_id if old_line is not None else (entity.model_id if entity else None)
        matched_current = any(
            old_line is not None
            and line.key == old_line.key
            and line.model_id == model_id
            and line.route_step_id == event.route_step_id
            and (line.row_id is None or line.row_id == row_id)
            for line in current_lines
        )
        if matched_current:
            continue
        source_key = old_line.key if old_line is not None else "NO_PLAN_LINE"
        key = f"UNPLANNED:{source_key}:{step.code}:{row_id}"
        norm = standard_norms.get(step.id)
        qty, existing_norm = groups.get(key, (Decimal(0), norm))
        groups[key] = (qty + Decimal(1), existing_norm)
    return [PlanLineMetric(key=key, planned_qty=Decimal(0), fact_qty=qty, norm_minutes=norm) for key, (qty, norm) in sorted(groups.items())]


def _row_plan_lines(db: Session, plan_id: str, row_id: str) -> list[PlanLine]:
    return list(db.scalars(
        select(PlanLine)
        .join(RouteStep, RouteStep.id == PlanLine.route_step_id)
        .where(
            PlanLine.plan_version_id == plan_id,
            (
                (PlanLine.row_id == row_id)
                | (PlanLine.row_id.is_(None) & (RouteStep.row_id == row_id))
            ),
        )
        .order_by(PlanLine.key)
    ))


def _fact_count_for_row(db: Session, line: PlanLine, shift_id: str, row_id: str) -> Decimal:
    correction = aliased(OperationEvent)
    count = db.scalar(
        select(func.count()).select_from(OperationEvent)
        .join(PlanLine, PlanLine.id == OperationEvent.plan_line_id)
        .join(WorkSession, WorkSession.id == OperationEvent.work_session_id)
        .where(
            OperationEvent.shift_id == shift_id,
            WorkSession.row_id == row_id,
            PlanLine.key == line.key,
            PlanLine.model_id == line.model_id,
            PlanLine.route_step_id == line.route_step_id,
            OperationEvent.status == "ACCEPTED",
            OperationEvent.event_type == "COMPLETE",
            OperationEvent.attempt_type == "PRIMARY",
            OperationEvent.correction_of_id.is_(None),
            ~select(correction.id).where(
                correction.correction_of_id == OperationEvent.id,
                correction.status == "ACCEPTED",
            ).exists(),
        )
    )
    return Decimal(count or 0)


def _row_line_inputs(db: Session, lines: list[PlanLine], shift_id: str, row_id: str) -> list[PlanLineMetric]:
    return [
        PlanLineMetric(
            key=line.key,
            planned_qty=Decimal(line.planned_qty),
            fact_qty=_fact_count_for_row(db, line, shift_id, row_id),
            norm_minutes=Decimal(line.norm_minutes) if line.norm_minutes is not None else None,
        )
        for line in lines
    ]


def _row_unplanned_inputs(
    db: Session,
    *,
    shift_id: str,
    row_id: str,
    current_lines: list[PlanLine],
    standard: StandardSetVersion,
) -> list[PlanLineMetric]:
    standard_norms = {
        value.route_step_id: Decimal(value.norm_minutes)
        for value in db.scalars(select(StandardValue).where(StandardValue.standard_set_id == standard.id))
    }
    groups: dict[str, tuple[Decimal, Decimal | None]] = {}
    correction = aliased(OperationEvent)
    events = db.scalars(
        select(OperationEvent)
        .join(WorkSession, WorkSession.id == OperationEvent.work_session_id)
        .where(
            OperationEvent.shift_id == shift_id,
            WorkSession.row_id == row_id,
            OperationEvent.status == "ACCEPTED",
            OperationEvent.event_type == "COMPLETE",
            OperationEvent.attempt_type == "PRIMARY",
            OperationEvent.correction_of_id.is_(None),
            ~select(correction.id).where(
                correction.correction_of_id == OperationEvent.id,
                correction.status == "ACCEPTED",
            ).exists(),
        )
    )
    for event in events:
        old_line = db.get(PlanLine, event.plan_line_id) if event.plan_line_id else None
        entity = db.get(TrackedEntity, event.entity_id)
        model_id = old_line.model_id if old_line is not None else (entity.model_id if entity else None)
        matched_current = any(
            old_line is not None
            and line.key == old_line.key
            and line.model_id == model_id
            and line.route_step_id == event.route_step_id
            for line in current_lines
        )
        if matched_current:
            continue
        step = db.get(RouteStep, event.route_step_id)
        if step is None:
            continue
        source_key = old_line.key if old_line is not None else "NO_PLAN_LINE"
        key = f"UNPLANNED:{source_key}:{step.code}:{row_id}"
        norm = standard_norms.get(step.id)
        qty, existing_norm = groups.get(key, (Decimal(0), norm))
        groups[key] = (qty + Decimal(1), existing_norm)
    return [
        PlanLineMetric(key=key, planned_qty=Decimal(0), fact_qty=qty, norm_minutes=norm)
        for key, (qty, norm) in sorted(groups.items())
    ]


def _hours_for_row(db: Session, shift_id: str, row_id: str) -> Decimal:
    correction = aliased(TimeEntry)
    value = db.scalar(
        select(func.coalesce(func.sum(TimeEntry.hours), 0))
        .join(ShiftAssignment, ShiftAssignment.id == TimeEntry.assignment_id)
        .where(
            ShiftAssignment.shift_id == shift_id,
            ShiftAssignment.row_id == row_id,
            TimeEntry.approval_status == "APPROVED",
            TimeEntry.category != "UNAVAILABLE",
            ~select(correction.id).where(correction.supersedes_id == TimeEntry.id).exists(),
        )
    )
    return Decimal(value or 0)


def _eligible_primary_events_for_row(
    db: Session,
    shift_id: str,
    row_id: str,
    route_step_ids: set[str],
) -> list[OperationEvent]:
    if not route_step_ids:
        return []
    correction = aliased(OperationEvent)
    return list(db.scalars(
        select(OperationEvent)
        .join(WorkSession, WorkSession.id == OperationEvent.work_session_id)
        .where(
            OperationEvent.shift_id == shift_id,
            WorkSession.row_id == row_id,
            OperationEvent.route_step_id.in_(route_step_ids),
            OperationEvent.status == "ACCEPTED",
            OperationEvent.event_type == "COMPLETE",
            OperationEvent.attempt_type == "PRIMARY",
            OperationEvent.correction_of_id.is_(None),
            ~select(correction.id).where(
                correction.correction_of_id == OperationEvent.id,
                correction.status == "ACCEPTED",
            ).exists(),
        )
    ))


def calculate_row_metrics(db: Session, shift_id: str, row_id: str) -> dict[str, Any]:
    """Calculate honest row-scoped metrics without inventing row quality."""

    shift = db.get(Shift, shift_id)
    if shift is None:
        raise APIError(404, "SHIFT_NOT_FOUND", "Смена не найдена")
    row = db.get(ProductionRow, row_id)
    if row is None:
        raise APIError(404, "ROW_NOT_FOUND", "Производственный ряд не найден")
    plan = latest_approved_plan(db, shift_id)
    standard = db.get(StandardSetVersion, plan.standard_version_id)
    if standard is None:
        raise APIError(409, "PLAN_STANDARD_MISSING", "Версия норм, закреплённая за планом, не найдена")
    lines = _row_plan_lines(db, plan.id, row.id)
    line_inputs = _row_line_inputs(db, lines, shift_id, row.id)
    line_inputs += _row_unplanned_inputs(
        db,
        shift_id=shift_id,
        row_id=row.id,
        current_lines=lines,
        standard=standard,
    )
    h_accounted = _hours_for_row(db, shift_id, row.id)
    trace = {
        "plan_version_id": plan.id,
        "plan_version": plan.version,
        "standard_version_id": standard.id,
        "standard_version": standard.version,
        "methodology": "DEMO-METHOD-V1",
        "synthetic": True,
    }

    if row.category != "QC":
        metrics = calculate_kpi(ProductionInputs(
            plan_lines=line_inputs,
            h_accounted_hours=h_accounted,
            rho_target=Decimal(shift.rho_target),
            quality_eligible_norm_hours=None,
            first_pass_good_norm_hours=None,
            maturity_state=shift.maturity_state,
            q_min=Decimal(shift.q_min),
            critical_quality_hold="CRITICAL_QUALITY_HOLD" in shift.reason_flags,
            h_rework_hours=None,
        ))
        reasons = sorted(set(metrics.reasons) | {"ROW_QUALITY_NOT_ATTRIBUTABLE"})
        return {
            "row_id": row.id,
            "row_code": row.code,
            "category": row.category,
            "a_plan": decimal_string(metrics.a_plan) if metrics.a_plan is not None else None,
            "a_volume": decimal_string(metrics.a_volume) if metrics.a_volume is not None else None,
            "p": decimal_string(metrics.p_raw) if metrics.p_raw is not None else None,
            "h_accounted_hours": decimal_string(h_accounted),
            "q": None,
            "kpi_raw": None,
            "kpi_official": None,
            "reason_flags": reasons,
            "inputs": json_ready({
                "e_fact": metrics.e_fact,
                "e_plan": metrics.e_plan,
                "e_plan_covered": metrics.e_plan_covered,
                "rho_target": Decimal(shift.rho_target),
            }),
            "trace": trace,
        }

    primary_events = _eligible_primary_events_for_row(
        db,
        shift_id,
        row.id,
        {line.route_step_id for line in lines},
    )
    eligible_ids = {event.id for event in primary_events}
    decisions = list(db.scalars(select(QualityDecision).where(QualityDecision.shift_id == shift_id)))
    primary_decisions = [decision for decision in decisions if decision.operation_event_id in eligible_ids]
    decision_ids = [decision.id for decision in primary_decisions]
    audits = list(db.scalars(select(QualityAudit).where(QualityAudit.decision_id.in_(decision_ids)))) if decision_ids else []
    completeness: list[str] = []
    if len(primary_decisions) != len(primary_events):
        completeness.append("INCOMPLETE_DECISION_COHORT")
    otk = calculate_otk_kpi(OtkInputs(
        plan_lines=line_inputs,
        h_accounted_hours=h_accounted,
        rho_target=Decimal(shift.rho_target),
        audited_correct=Decimal(sum(1 for audit in audits if audit.result == "CONFIRMED")),
        audited_total=Decimal(len(audits)),
        sampling_valid=shift.audit_sampling_valid,
        coverage_inspected=Decimal(len(primary_decisions)),
        coverage_due=Decimal(len(primary_events)),
        timely_decisions=None,
        decisions_due=None,
        maturity_state=shift.maturity_state,
        min_audit_size=Decimal(shift.min_audit_size),
        completeness_errors=tuple(completeness),
    ))
    return {
        "row_id": row.id,
        "row_code": row.code,
        "category": row.category,
        "a_plan": decimal_string(otk.a_plan) if otk.a_plan is not None else None,
        "a_volume": decimal_string(otk.a_volume) if otk.a_volume is not None else None,
        "p": decimal_string(otk.p_raw) if otk.p_raw is not None else None,
        "h_accounted_hours": decimal_string(h_accounted),
        "q": decimal_string(otk.q_decision) if otk.q_decision is not None else None,
        "kpi_raw": decimal_string(otk.kpi_raw) if otk.kpi_raw is not None else None,
        "kpi_official": decimal_string(otk.kpi_official) if otk.kpi_official is not None else None,
        "reason_flags": list(otk.reasons),
        "inputs": json_ready({
            "e_fact": otk.e_fact,
            "e_plan": otk.e_plan,
            "e_plan_covered": otk.e_plan_covered,
            "rho_target": Decimal(shift.rho_target),
            "audited_correct": Decimal(sum(1 for audit in audits if audit.result == "CONFIRMED")),
            "audited_total": Decimal(len(audits)),
            "coverage_inspected": Decimal(len(primary_decisions)),
            "coverage_due": Decimal(len(primary_events)),
        }),
        "trace": trace,
    }


def calculate_shift(db: Session, shift_id: str) -> dict[str, Any]:
    shift = db.get(Shift, shift_id)
    if shift is None:
        raise APIError(404, "SHIFT_NOT_FOUND", "Смена не найдена")
    plan = latest_approved_plan(db, shift_id)
    lines = list(db.scalars(select(PlanLine).where(PlanLine.plan_version_id == plan.id).order_by(PlanLine.key)))
    if not lines:
        raise APIError(409, "PLAN_EMPTY", "Утверждённый план не содержит строк")
    standard = db.get(StandardSetVersion, plan.standard_version_id)
    if standard is None:
        raise APIError(409, "PLAN_STANDARD_MISSING", "Версия норм, закреплённая за планом, не найдена")

    step_categories = {
        line.id: db.scalar(select(RouteStep.code).where(RouteStep.id == line.route_step_id)) or ""
        for line in lines
    }
    production_lines = [line for line in lines if "QC" not in step_categories[line.id]]
    qc_lines = [line for line in lines if "QC" in step_categories[line.id]]

    qc_norm_by_key = {line.key: (Decimal(line.norm_minutes) / Decimal(60) if line.norm_minutes is not None else None) for line in qc_lines}

    def event_qc_norm(event: OperationEvent) -> Decimal | None:
        old_line = db.get(PlanLine, event.plan_line_id) if event.plan_line_id else None
        if old_line is None:
            value = db.scalar(select(StandardValue).where(StandardValue.standard_set_id == standard.id, StandardValue.route_step_id == event.route_step_id))
            return Decimal(value.norm_minutes) / Decimal(60) if value else None
        current = qc_norm_by_key.get(old_line.key)
        if old_line.key in qc_norm_by_key:
            return current
        value = db.scalar(select(StandardValue).where(StandardValue.standard_set_id == standard.id, StandardValue.route_step_id == event.route_step_id))
        return Decimal(value.norm_minutes) / Decimal(60) if value else None

    qc_correction = aliased(OperationEvent)
    all_primary_qc_events = list(db.scalars(
        select(OperationEvent).join(RouteStep, RouteStep.id == OperationEvent.route_step_id).where(
            OperationEvent.shift_id == shift_id,
            OperationEvent.status == "ACCEPTED",
            OperationEvent.event_type == "COMPLETE",
            OperationEvent.attempt_type == "PRIMARY",
            RouteStep.code.like("%QC%"),
            OperationEvent.correction_of_id.is_(None),
            ~select(qc_correction.id).where(
                qc_correction.correction_of_id == OperationEvent.id,
                qc_correction.status == "ACCEPTED",
            ).exists(),
        )
    ))
    eligible_qc_event_ids = {event.id for event in all_primary_qc_events}
    decisions = list(db.scalars(select(QualityDecision).where(QualityDecision.shift_id == shift_id)))
    primary_decisions = []
    for decision in decisions:
        event = db.get(OperationEvent, decision.operation_event_id)
        if event is not None and event.id in eligible_qc_event_ids:
            primary_decisions.append((decision, event))
    quality_norms = [event_qc_norm(event) for event in all_primary_qc_events]
    quality_eligible = None if any(norm is None for norm in quality_norms) else sum((norm for norm in quality_norms if norm is not None), Decimal(0))
    first_pass_good = sum(
        (norm for decision, event in primary_decisions if decision.decision == "ACCEPT" and (norm := event_qc_norm(event)) is not None),
        Decimal(0),
    )
    production_completeness = [flag for flag in shift.reason_flags if flag == "INCOMPLETE_DATA"]
    if len(primary_decisions) != len(all_primary_qc_events):
        production_completeness.append("INCOMPLETE_QUALITY_COHORT")
    if quality_eligible is None:
        production_completeness.append("MISSING_QUALITY_NORM")

    h_production = _hours_for_step_category(db, shift_id, "ASSEMBLY") + _hours_for_step_category(db, shift_id, "SOLDER")
    h_rework = _hours_for_categories(db, shift_id, ["REWORK"], ["ASSEMBLY", "SOLDER"])
    prod = calculate_kpi(ProductionInputs(
        plan_lines=_line_inputs(db, production_lines, shift_id) + _unplanned_inputs(db, shift_id=shift_id, current_lines=production_lines, standard=standard, qc=False),
        h_accounted_hours=h_production,
        rho_target=Decimal(shift.rho_target),
        quality_eligible_norm_hours=quality_eligible,
        first_pass_good_norm_hours=first_pass_good,
        maturity_state=shift.maturity_state,
        q_min=Decimal(shift.q_min),
        critical_quality_hold="CRITICAL_QUALITY_HOLD" in shift.reason_flags,
        h_rework_hours=h_rework,
        completeness_errors=tuple(production_completeness),
    ))

    audits = list(db.scalars(
        select(QualityAudit).join(QualityDecision, QualityDecision.id == QualityAudit.decision_id).where(QualityDecision.shift_id == shift_id)
    ))
    audited_total = Decimal(len(audits))
    audited_correct = Decimal(sum(1 for audit in audits if audit.result == "CONFIRMED"))
    otk_completeness = [flag for flag in shift.reason_flags if flag == "INCOMPLETE_DATA"]
    if len(primary_decisions) != len(all_primary_qc_events):
        otk_completeness.append("INCOMPLETE_DECISION_COHORT")
    otk = calculate_otk_kpi(OtkInputs(
        plan_lines=_line_inputs(db, qc_lines, shift_id) + _unplanned_inputs(db, shift_id=shift_id, current_lines=qc_lines, standard=standard, qc=True),
        h_accounted_hours=_hours_for_step_category(db, shift_id, "QC"),
        rho_target=Decimal(shift.rho_target),
        audited_correct=audited_correct,
        audited_total=audited_total,
        sampling_valid=shift.audit_sampling_valid,
        coverage_inspected=Decimal(len(primary_decisions)),
        coverage_due=Decimal(len(all_primary_qc_events)),
        timely_decisions=None,
        decisions_due=None,
        maturity_state=shift.maturity_state,
        min_audit_size=Decimal(shift.min_audit_size),
        completeness_errors=tuple(otk_completeness),
    ))

    production = json_ready(asdict(prod))
    otc = json_ready(asdict(otk))
    response = {
        "shift_id": shift.id,
        "approval_status": shift.approval_status,
        "maturity_state": shift.maturity_state,
        "reason_flags": sorted(set(shift.reason_flags) | set(prod.reasons) | set(otk.reasons)),
        "a_plan": production["a_plan"],
        "a_volume": production["a_volume"],
        "p": production["p_raw"],
        "q": production["q_fpy"],
        "kpi_raw": production["kpi_raw"],
        "kpi_official": production["kpi_official"],
        "production": production,
        "otk": otc,
        "inputs": {
            "h_accounted_hours": decimal_string(h_production),
            "h_rework_hours": decimal_string(h_rework),
            "rho_target": decimal_string(Decimal(shift.rho_target)),
            "q_min": decimal_string(Decimal(shift.q_min)),
            "audit_sampling_valid": shift.audit_sampling_valid,
            "min_audit_size": shift.min_audit_size,
        },
        "trace": {
            "plan_version_id": plan.id,
            "plan_version": plan.version,
            "standard_version_id": standard.id,
            "standard_version": standard.version,
            "methodology": "DEMO-METHOD-V1",
            "synthetic": True,
        },
        "version": shift.version,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }
    return response


def calculation_input_hash(metrics: dict[str, Any]) -> str:
    stable = {key: value for key, value in metrics.items() if key != "calculated_at"}
    return canonical_payload_hash(stable)

"""Deterministic synthetic portfolio data. Never resets data unless --reset is explicit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Base, configure_database, create_schema, get_engine
from app.models import (
    AuditEvent,
    Employee,
    GenealogyLink,
    OperationEvent,
    OperationProjection,
    PlanLine,
    ProductionPlanVersion,
    ProductionRow,
    ProductModel,
    QualityAudit,
    QualityDecision,
    RouteStep,
    RouteVersion,
    Shift,
    ShiftAssignment,
    StandardSetVersion,
    StandardValue,
    TimeEntry,
    TrackedEntity,
    User,
    UserRole,
    WorkSession,
    Workstation,
)
from app.security import hash_password

DEMO_PASSWORD = "Demo2026!"


def _id(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"kpd-demo:{name}"))


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 25, hour, minute, tzinfo=timezone.utc)


def _add(db: Session, obj):
    db.add(obj)
    db.flush()
    return obj


def seed_demo(db: Session) -> bool:
    """Seed an empty database. Return False without modifying an existing database."""
    if db.scalar(select(func.count()).select_from(User)):
        return False

    row_specs = [
        ("DEMO-ASM-01", "Сборка 1", "ASSEMBLY"),
        ("DEMO-ASM-02", "Сборка 2", "ASSEMBLY"),
        ("DEMO-ASM-03", "Сборка 3", "ASSEMBLY"),
        ("DEMO-SOLDER-01", "Пайка", "SOLDER"),
        ("DEMO-QC-01", "ОТК", "QC"),
    ]
    rows: dict[str, ProductionRow] = {}
    stations: dict[str, Workstation] = {}
    for order, (code, name, category) in enumerate(row_specs, 1):
        row = _add(db, ProductionRow(id=_id(code), code=code, name=name, category=category, sort_order=order))
        rows[code] = row
        station = _add(db, Workstation(id=_id(f"WS:{code}"), code=f"WS-{code}", name=f"Терминал {name}", row_id=row.id))
        stations[code] = station

    model = _add(db, ProductModel(id=_id("MODEL-Q1"), code="DEMO-QUAD-Q1", name="ДЕМО квадрокоптер Q1", is_demo=True))
    route = _add(db, RouteVersion(id=_id("ROUTE-Q1-V1"), model_id=model.id, version=1, status="APPROVED"))
    step_specs = [
        ("SOLDER", "Пайка контроллера", 1, rows["DEMO-SOLDER-01"].id, "WIP"),
        ("ASSEMBLE", "Сборка", 2, None, "WIP"),
        ("QC", "Первичный контроль ОТК", 3, rows["DEMO-QC-01"].id, "WIP"),
        ("FINALIZE", "Присвоение final serial", 4, rows["DEMO-QC-01"].id, "WIP"),
    ]
    steps: dict[str, RouteStep] = {}
    for code, name, sequence, row_id, entity_type in step_specs:
        steps[code] = _add(db, RouteStep(
            id=_id(f"STEP:{code}"), route_version_id=route.id, code=f"DEMO-{code}", name=name,
            sequence=sequence, row_id=row_id, entity_type=entity_type, allows_rework=code != "FINALIZE",
        ))

    shift = _add(db, Shift(
        id=_id("SHIFT"), code="DEMO-SHIFT-2026-10-25-D", production_date="2026-10-25",
        starts_at=_dt(5), ends_at=_dt(13), status="RUNNING", approval_status="DRAFT",
        maturity_state="FINAL", reason_flags=["SYNTHETIC_DEMO_DATA"], version=1,
        rho_target=Decimal("1"), q_min=Decimal("0.6"), audit_sampling_valid=True, min_audit_size=1,
    ))

    user_specs = [
        ("assembly1", "Оператор сборки 1", "WORKER", "DEMO-ASM-01", "ASSEMBLE"),
        ("assembly2", "Оператор сборки 2", "WORKER", "DEMO-ASM-02", "ASSEMBLE"),
        ("assembly3", "Оператор сборки 3", "WORKER", "DEMO-ASM-03", "ASSEMBLE"),
        ("solder", "Оператор пайки", "WORKER", "DEMO-SOLDER-01", "SOLDER"),
        ("qc", "Контролёр ОТК", "QC", "DEMO-QC-01", "QC"),
        ("foreman", "Бригадир", "FOREMAN", "DEMO-ASM-01", None),
        ("auditor", "Независимый аудитор", "AUDITOR", None, None),
        ("planner", "Планировщик", "PLANNER", None, None),
        ("supervisor", "Руководитель смены", "SUPERVISOR", None, None),
        ("admin", "Администратор ДЕМО", "ADMIN", None, None),
    ]
    users: dict[str, User] = {}
    assignments: dict[str, ShiftAssignment] = {}
    sessions: dict[str, WorkSession] = {}
    shared_hash = hash_password(DEMO_PASSWORD)
    for idx, (username, display_name, role, row_code, step_code) in enumerate(user_specs, 1):
        employee = _add(db, Employee(
            id=_id(f"EMP:{username}"), code=f"DEMO-E-{idx:02}", display_name=display_name, status="ACTIVE",
        ))
        user = _add(db, User(
            id=_id(f"USER:{username}"), username=username, password_hash=shared_hash,
            display_name=display_name, employee_id=employee.id, is_active=True,
        ))
        users[username] = user
        _add(db, UserRole(id=_id(f"ROLE:{username}"), user_id=user.id, role=role, row_id=rows[row_code].id if row_code else None))
        if row_code and step_code:
            assignment = _add(db, ShiftAssignment(
                id=_id(f"ASSIGN:{username}"), shift_id=shift.id, employee_id=employee.id,
                row_id=rows[row_code].id, workstation_id=stations[row_code].id,
                route_step_id=steps[step_code].id, starts_at=shift.starts_at, ends_at=shift.ends_at, status="ACTIVE",
            ))
            assignments[username] = assignment
            sessions[username] = _add(db, WorkSession(
                id=_id(f"WORKSESSION:{username}"), user_id=user.id, employee_id=employee.id,
                shift_id=shift.id, row_id=assignment.row_id, workstation_id=assignment.workstation_id,
                route_step_id=assignment.route_step_id, assignment_id=assignment.id, started_at=shift.starts_at,
            ))
            _add(db, TimeEntry(
                id=_id(f"TIME:{username}"), assignment_id=assignment.id,
                category="PRIMARY", hours=Decimal("8"), source="DEMO_LEDGER", approval_status="APPROVED", version=1,
            ))

    # A foreman assignment makes roster editing and genealogy demonstrations concrete.
    foreman_emp = users["foreman"].employee_id
    foreman_assignment = _add(db, ShiftAssignment(
        id=_id("ASSIGN:foreman"), shift_id=shift.id, employee_id=foreman_emp,
        row_id=rows["DEMO-ASM-01"].id, workstation_id=stations["DEMO-ASM-01"].id,
        route_step_id=steps["ASSEMBLE"].id, starts_at=shift.starts_at, ends_at=shift.ends_at, status="ACTIVE",
    ))
    _add(db, TimeEntry(id=_id("TIME:foreman"), assignment_id=foreman_assignment.id, category="SUPPORT", hours=Decimal("8"), source="DEMO_LEDGER", approval_status="APPROVED", version=1))

    standard = _add(db, StandardSetVersion(
        id=_id("STANDARD-V1"), model_id=model.id, version=1, status="APPROVED",
        effective_from=shift.starts_at, approved_at=shift.starts_at, approved_by_id=users["admin"].id,
    ))
    norms = {"SOLDER": Decimal("6"), "ASSEMBLE": Decimal("12"), "QC": Decimal("4"), "FINALIZE": Decimal("1")}
    for code, minutes in norms.items():
        _add(db, StandardValue(id=_id(f"STANDARD-V1:{code}"), standard_set_id=standard.id, route_step_id=steps[code].id, norm_minutes=minutes))

    plan = _add(db, ProductionPlanVersion(
        id=_id("PLAN-V1"), shift_id=shift.id, standard_version_id=standard.id, version=1, status="APPROVED",
        approved_at=shift.starts_at, approved_by_id=users["planner"].id, reason="Синтетический план портфолио",
    ))
    plan_specs = [
        ("SOLDER", None, 6),
        ("ASSEMBLE", "DEMO-ASM-01", 2),
        ("ASSEMBLE", "DEMO-ASM-02", 2),
        ("ASSEMBLE", "DEMO-ASM-03", 2),
        ("QC", None, 6),
    ]
    plan_lines: dict[tuple[str, str | None], PlanLine] = {}
    for code, row_code, qty in plan_specs:
        key = f"{code}:{row_code or 'ALL'}"
        line = _add(db, PlanLine(
            id=_id(f"PLANLINE:{key}"), plan_version_id=plan.id, key=key, model_id=model.id,
            route_step_id=steps[code].id, row_id=rows[row_code].id if row_code else None,
            planned_qty=qty, norm_minutes=norms[code],
        ))
        plan_lines[(code, row_code)] = line

    entities: dict[str, TrackedEntity] = {}
    for n in range(1, 9):
        qr = f"DEMO-WIP-{n:03}"
        entities[qr] = _add(db, TrackedEntity(
            id=_id(qr), qr_code=qr, entity_type="WIP", model_id=model.id,
            route_version_id=route.id, status="IN_PROGRESS",
        ))
    for qr in ["DEMO-COMP-FC-001", "DEMO-COMP-MOTOR-003A", "DEMO-COMP-MOTOR-003B", "DEMO-COMP-MOTOR-004A", "DEMO-COMP-MOTOR-004B"]:
        entities[qr] = _add(db, TrackedEntity(id=_id(qr), qr_code=qr, entity_type="COMPONENT", status="ACTIVE"))
    final = _add(db, TrackedEntity(
        id=_id("DEMO-FINAL-001"), qr_code="DEMO-FINAL-001", entity_type="FINAL",
        model_id=model.id, route_version_id=route.id, status="FINISHED", final_serial="DEMO-FINAL-001",
    ))

    def add_event(qr: str, code: str, username: str, row_code: str | None, attempt_type: str = "PRIMARY", attempt_no: int = 1) -> OperationEvent:
        entity = entities[qr]
        line = plan_lines.get((code, row_code)) or plan_lines.get((code, None))
        event = _add(db, OperationEvent(
            id=_id(f"EVENT:{qr}:{code}:{attempt_type}:{attempt_no}"), payload_hash=_id(f"HASH:{qr}:{code}:{attempt_type}:{attempt_no}"),
            shift_id=shift.id, work_session_id=sessions[username].id, entity_id=entity.id,
            route_step_id=steps[code].id, plan_line_id=line.id if line else None, user_id=users[username].id,
            attempt_no=attempt_no, attempt_type=attempt_type, event_type="COMPLETE", outcome="COMPLETED",
            status="ACCEPTED", code="EVENT_ACCEPTED", server_received_at=_dt(6, attempt_no),
        ))
        projection = db.scalar(select(OperationProjection).where(OperationProjection.entity_id == entity.id))
        if projection is None:
            projection = OperationProjection(
                id=_id(f"PROJECTION:{qr}"), entity_id=entity.id, last_event_id=event.id,
                last_route_step_id=steps[code].id, route_position=steps[code].sequence,
                status="FINISHED" if code == "FINALIZE" else "IN_PROGRESS", version=1,
            )
            db.add(projection)
        else:
            projection.last_event_id = event.id
            projection.last_route_step_id = steps[code].id
            projection.route_position = steps[code].sequence
            projection.version += 1
        db.flush()
        return event

    qc_events: dict[str, OperationEvent] = {}
    for qr, assembly_user, assembly_row in [
        ("DEMO-WIP-001", "assembly1", "DEMO-ASM-01"),
        ("DEMO-WIP-002", "assembly2", "DEMO-ASM-02"),
        ("DEMO-WIP-003", "assembly3", "DEMO-ASM-03"),
    ]:
        add_event(qr, "SOLDER", "solder", None)
        add_event(qr, "ASSEMBLE", assembly_user, assembly_row)
        qc_events[qr] = add_event(qr, "QC", "qc", None)

    # Immutable genealogy history: active component, replaced component, and WIP→final.
    _add(db, GenealogyLink(
        id=_id("GEN:FC1"), request_id=_id("REQ:GEN:FC1"), action="ATTACH",
        parent_entity_id=entities["DEMO-WIP-001"].id, child_entity_id=entities["DEMO-COMP-FC-001"].id,
        active=True, created_by_id=users["foreman"].id, created_at=_dt(5, 30),
    ))
    _add(db, GenealogyLink(
        id=_id("GEN:M3A"), request_id=_id("REQ:GEN:M3A"), action="ATTACH",
        parent_entity_id=entities["DEMO-WIP-003"].id, child_entity_id=entities["DEMO-COMP-MOTOR-003A"].id,
        active=False, reason="ДЕМО замена", created_by_id=users["foreman"].id, created_at=_dt(5, 35), ended_at=_dt(6),
    ))
    _add(db, GenealogyLink(
        id=_id("GEN:M3B"), request_id=_id("REQ:GEN:M3B"), action="REPLACE",
        parent_entity_id=entities["DEMO-WIP-003"].id, child_entity_id=entities["DEMO-COMP-MOTOR-003B"].id,
        active=True, reason="ДЕМО замена", created_by_id=users["foreman"].id, created_at=_dt(6),
    ))
    _add(db, GenealogyLink(
        id=_id("GEN:FINAL1"), request_id=_id("REQ:GEN:FINAL1"), action="FINALIZE",
        parent_entity_id=final.id, child_entity_id=entities["DEMO-WIP-001"].id,
        active=True, created_by_id=users["foreman"].id, created_at=_dt(7),
    ))
    entities["DEMO-WIP-001"].status = "FINISHED"

    decisions: list[QualityDecision] = []
    for idx, qr in enumerate(["DEMO-WIP-001", "DEMO-WIP-002", "DEMO-WIP-003"], 1):
        decision = _add(db, QualityDecision(
            id=_id(f"QCDEC:{idx}"), request_id=_id(f"REQ:QCDEC:{idx}"), entity_id=entities[qr].id,
            shift_id=shift.id, operation_event_id=qc_events[qr].id, inspector_user_id=users["qc"].id,
            decision="REJECT" if idx == 2 else "ACCEPT", defect_code="DEMO-JOINT" if idx == 2 else None,
            note="Синтетическое решение", created_at=_dt(8, idx),
        ))
        decisions.append(decision)
        _add(db, QualityAudit(
            id=_id(f"QCAUD:{idx}"), request_id=_id(f"REQ:QCAUD:{idx}"), decision_id=decision.id,
            auditor_user_id=users["auditor"].id, result="CONFIRMED", note="Независимый ДЕМО-аудит", created_at=_dt(9, idx),
        ))

    _add(db, AuditEvent(
        id=_id("AUDIT:SEED"), actor_user_id=users["admin"].id, action="DEMO_SEEDED",
        object_type="database", object_id="DEMO", after={"synthetic": True, "version": 1},
        reason="Explicit deterministic seed", trace_id=_id("TRACE:SEED"), created_at=_dt(4),
    ))
    db.commit()
    return True


def upgrade_demo_foreman_scope(db: Session) -> bool:
    """Idempotently scope the legacy DEMO foreman role without resetting data."""
    foreman = db.scalar(select(User).where(User.username == "foreman"))
    row = db.scalar(select(ProductionRow).where(ProductionRow.code == "DEMO-ASM-01"))
    if foreman is None or row is None:
        return False
    role = db.scalar(select(UserRole).where(UserRole.user_id == foreman.id, UserRole.role == "FOREMAN"))
    if role is None or role.row_id == row.id:
        return False
    if role.row_id is not None:
        # Never overwrite an explicit non-DEMO scope choice.
        return False
    role.row_id = row.id
    db.add(AuditEvent(
        id=_id("AUDIT:FOREMAN-SCOPE-V1"), actor_user_id=None,
        action="DEMO_FOREMAN_SCOPE_UPGRADED", object_type="user_role", object_id=role.id,
        before={"row_id": None}, after={"row_id": row.id, "row_code": row.code, "synthetic": True},
        reason="Idempotent DEMO data upgrade; no reset", trace_id=_id("TRACE:FOREMAN-SCOPE-V1"),
    ))
    db.commit()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Create deterministic synthetic demo data")
    parser.add_argument("--reset", action="store_true", help="Explicitly delete all demo database tables before seeding")
    args = parser.parse_args()
    configure_database()
    if args.reset:
        Base.metadata.drop_all(get_engine())
    create_schema()
    from app.db import SessionLocal
    assert SessionLocal is not None
    with SessionLocal() as db:
        created = seed_demo(db)
        upgraded = upgrade_demo_foreman_scope(db)
        print("DEMO seeded" if created else "DEMO foreman scope upgraded" if upgraded else "DEMO already exists; unchanged")


if __name__ == "__main__":
    main()

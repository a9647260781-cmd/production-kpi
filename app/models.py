from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    employee: Mapped[Employee | None] = relationship()
    roles: Mapped[list[UserRole]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ProductionRow(Base, TimestampMixin):
    __tablename__ = "production_rows"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class UserRole(Base):
    __tablename__ = "user_roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    row_id: Mapped[str | None] = mapped_column(ForeignKey("production_rows.id"), nullable=True)
    user: Mapped[User] = relationship(back_populates="roles")
    row: Mapped[ProductionRow | None] = relationship()
    __table_args__ = (UniqueConstraint("user_id", "role", "row_id", name="uq_user_role_scope"),)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship()


class Workstation(Base, TimestampMixin):
    __tablename__ = "workstations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    row_id: Mapped[str] = mapped_column(ForeignKey("production_rows.id"), nullable=False)
    row: Mapped[ProductionRow] = relationship()


class ProductModel(Base, TimestampMixin):
    __tablename__ = "product_models"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RouteVersion(Base, TimestampMixin):
    __tablename__ = "route_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(ForeignKey("product_models.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="APPROVED")
    model: Mapped[ProductModel] = relationship()
    steps: Mapped[list[RouteStep]] = relationship(back_populates="route", order_by="RouteStep.sequence")
    __table_args__ = (UniqueConstraint("model_id", "version", name="uq_route_model_version"),)


class RouteStep(Base, TimestampMixin):
    __tablename__ = "route_steps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    route_version_id: Mapped[str] = mapped_column(ForeignKey("route_versions.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    row_id: Mapped[str | None] = mapped_column(ForeignKey("production_rows.id"), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False, default="WIP")
    allows_rework: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    route: Mapped[RouteVersion] = relationship(back_populates="steps")
    row: Mapped[ProductionRow | None] = relationship()
    __table_args__ = (
        UniqueConstraint("route_version_id", "code", name="uq_route_step_code"),
        UniqueConstraint("route_version_id", "sequence", name="uq_route_step_sequence"),
    )


class Shift(Base, TimestampMixin):
    __tablename__ = "shifts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    production_date: Mapped[str] = mapped_column(String(10), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="RUNNING", nullable=False)
    approval_status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False)
    maturity_state: Mapped[str] = mapped_column(String(24), default="PROVISIONAL", nullable=False)
    reason_flags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    rho_target: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("1"), nullable=False)
    q_min: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0.6"), nullable=False)
    audit_sampling_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    min_audit_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ShiftAssignment(Base, TimestampMixin):
    __tablename__ = "shift_assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shift_id: Mapped[str] = mapped_column(ForeignKey("shifts.id"), nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    row_id: Mapped[str] = mapped_column(ForeignKey("production_rows.id"), nullable=False)
    workstation_id: Mapped[str] = mapped_column(ForeignKey("workstations.id"), nullable=False)
    route_step_id: Mapped[str] = mapped_column(ForeignKey("route_steps.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    shift: Mapped[Shift] = relationship()
    employee: Mapped[Employee] = relationship()
    row: Mapped[ProductionRow] = relationship()
    workstation: Mapped[Workstation] = relationship()
    route_step: Mapped[RouteStep] = relationship()


class TimeEntry(Base, TimestampMixin):
    __tablename__ = "time_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("shift_assignments.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="DEMO", nullable=False)
    approval_status: Mapped[str] = mapped_column(String(24), default="APPROVED", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("time_entries.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    assignment: Mapped[ShiftAssignment] = relationship(foreign_keys=[assignment_id])


class WorkSession(Base):
    __tablename__ = "work_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    shift_id: Mapped[str] = mapped_column(ForeignKey("shifts.id"), nullable=False)
    row_id: Mapped[str] = mapped_column(ForeignKey("production_rows.id"), nullable=False)
    workstation_id: Mapped[str] = mapped_column(ForeignKey("workstations.id"), nullable=False)
    route_step_id: Mapped[str] = mapped_column(ForeignKey("route_steps.id"), nullable=False)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("shift_assignments.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship()
    employee: Mapped[Employee] = relationship()
    shift: Mapped[Shift] = relationship()
    row: Mapped[ProductionRow] = relationship()
    workstation: Mapped[Workstation] = relationship()
    route_step: Mapped[RouteStep] = relationship()
    assignment: Mapped[ShiftAssignment] = relationship()


class TrackedEntity(Base, TimestampMixin):
    __tablename__ = "tracked_entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    qr_code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    model_id: Mapped[str | None] = mapped_column(ForeignKey("product_models.id"), nullable=True)
    route_version_id: Mapped[str | None] = mapped_column(ForeignKey("route_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    final_serial: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    model: Mapped[ProductModel | None] = relationship()
    route_version: Mapped[RouteVersion | None] = relationship()


class ProductionPlanVersion(Base, TimestampMixin):
    __tablename__ = "production_plan_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shift_id: Mapped[str] = mapped_column(ForeignKey("shifts.id"), nullable=False)
    standard_version_id: Mapped[str] = mapped_column(ForeignKey("standard_set_versions.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="APPROVED", nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("production_plan_versions.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    shift: Mapped[Shift] = relationship()
    lines: Mapped[list[PlanLine]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("shift_id", "version", name="uq_plan_shift_version"),)


class PlanLine(Base):
    __tablename__ = "plan_lines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("production_plan_versions.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    model_id: Mapped[str] = mapped_column(ForeignKey("product_models.id"), nullable=False)
    route_step_id: Mapped[str] = mapped_column(ForeignKey("route_steps.id"), nullable=False)
    row_id: Mapped[str | None] = mapped_column(ForeignKey("production_rows.id"), nullable=True)
    planned_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    norm_minutes: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    plan: Mapped[ProductionPlanVersion] = relationship(back_populates="lines")
    model: Mapped[ProductModel] = relationship()
    route_step: Mapped[RouteStep] = relationship()
    row: Mapped[ProductionRow | None] = relationship()
    __table_args__ = (UniqueConstraint("plan_version_id", "key", name="uq_plan_line_key"),)


class OperationEvent(Base):
    __tablename__ = "operation_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    shift_id: Mapped[str] = mapped_column(ForeignKey("shifts.id"), nullable=False)
    work_session_id: Mapped[str] = mapped_column(ForeignKey("work_sessions.id"), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("tracked_entities.id"), nullable=False)
    route_step_id: Mapped[str] = mapped_column(ForeignKey("route_steps.id"), nullable=False)
    plan_line_id: Mapped[str | None] = mapped_column(ForeignKey("plan_lines.id"), nullable=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attempt_type: Mapped[str] = mapped_column(String(24), default="PRIMARY", nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), default="COMPLETE", nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), default="COMPLETED", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACCEPTED", nullable=False)
    code: Mapped[str] = mapped_column(String(48), default="EVENT_ACCEPTED", nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    occurred_at_device: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correction_of_id: Mapped[str | None] = mapped_column(ForeignKey("operation_events.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    entity: Mapped[TrackedEntity] = relationship()
    route_step: Mapped[RouteStep] = relationship()
    plan_line: Mapped[PlanLine | None] = relationship()
    user: Mapped[User] = relationship()
    work_session: Mapped[WorkSession] = relationship()
    __table_args__ = (
        UniqueConstraint("entity_id", "route_step_id", "attempt_no", "attempt_type", "event_type", name="uq_semantic_operation_event"),
        Index("ix_operation_event_shift_received", "shift_id", "server_received_at"),
    )


class OperationProjection(Base, TimestampMixin):
    __tablename__ = "operation_projections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_id: Mapped[str] = mapped_column(ForeignKey("tracked_entities.id"), unique=True, nullable=False)
    last_event_id: Mapped[str] = mapped_column(ForeignKey("operation_events.id"), nullable=False)
    last_route_step_id: Mapped[str] = mapped_column(ForeignKey("route_steps.id"), nullable=False)
    route_position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="IN_PROGRESS", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    entity: Mapped[TrackedEntity] = relationship()
    last_event: Mapped[OperationEvent] = relationship(foreign_keys=[last_event_id])


class GenealogyLink(Base):
    __tablename__ = "genealogy_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    parent_entity_id: Mapped[str] = mapped_column(ForeignKey("tracked_entities.id"), nullable=False)
    child_entity_id: Mapped[str] = mapped_column(ForeignKey("tracked_entities.id"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("1"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(ForeignKey("operation_events.id"), nullable=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parent: Mapped[TrackedEntity] = relationship(foreign_keys=[parent_entity_id])
    child: Mapped[TrackedEntity] = relationship(foreign_keys=[child_entity_id])
    created_by: Mapped[User] = relationship()
    __table_args__ = (
        Index(
            "uq_genealogy_active_child",
            "child_entity_id",
            unique=True,
            sqlite_where=text("active = 1"),
            postgresql_where=text("active = true"),
        ),
    )


class StandardSetVersion(Base, TimestampMixin):
    __tablename__ = "standard_set_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(ForeignKey("product_models.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="APPROVED", nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("standard_set_versions.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    model: Mapped[ProductModel] = relationship()
    values: Mapped[list[StandardValue]] = relationship(back_populates="standard_set", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("model_id", "version", name="uq_standard_model_version"),)


class StandardValue(Base):
    __tablename__ = "standard_values"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    standard_set_id: Mapped[str] = mapped_column(ForeignKey("standard_set_versions.id"), nullable=False)
    route_step_id: Mapped[str] = mapped_column(ForeignKey("route_steps.id"), nullable=False)
    norm_minutes: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    standard_set: Mapped[StandardSetVersion] = relationship(back_populates="values")
    route_step: Mapped[RouteStep] = relationship()
    __table_args__ = (UniqueConstraint("standard_set_id", "route_step_id", name="uq_standard_route_step"),)


class QualityDecision(Base):
    __tablename__ = "quality_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("tracked_entities.id"), nullable=False)
    shift_id: Mapped[str] = mapped_column(ForeignKey("shifts.id"), nullable=False)
    operation_event_id: Mapped[str] = mapped_column(ForeignKey("operation_events.id"), unique=True, nullable=False)
    inspector_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    defect_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    entity: Mapped[TrackedEntity] = relationship()
    inspector: Mapped[User] = relationship()


class QualityAudit(Base):
    __tablename__ = "quality_audits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    decision_id: Mapped[str] = mapped_column(ForeignKey("quality_decisions.id"), nullable=False)
    auditor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    result: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    decision: Mapped[QualityDecision] = relationship()
    auditor: Mapped[User] = relationship()
    __table_args__ = (UniqueConstraint("decision_id", name="uq_quality_audit_decision"),)


class ReworkOrder(Base, TimestampMixin):
    __tablename__ = "rework_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("tracked_entities.id"), nullable=False)
    quality_decision_id: Mapped[str] = mapped_column(ForeignKey("quality_decisions.id"), nullable=False)
    requested_route_step_id: Mapped[str] = mapped_column(ForeignKey("route_steps.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    entity: Mapped[TrackedEntity] = relationship()
    decision: Mapped[QualityDecision] = relationship()
    requested_route_step: Mapped[RouteStep] = relationship()


class CalculationSnapshot(Base):
    __tablename__ = "calculation_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    shift_id: Mapped[str] = mapped_column(ForeignKey("shifts.id"), nullable=False)
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("production_plan_versions.id"), nullable=False)
    standard_version_id: Mapped[str] = mapped_column(ForeignKey("standard_set_versions.id"), nullable=False)
    shift_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    trace: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    approved_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("calculation_snapshots.id"), nullable=True)
    shift: Mapped[Shift] = relationship()
    __table_args__ = (UniqueConstraint("shift_id", "shift_version", name="uq_snapshot_shift_version"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor: Mapped[User | None] = relationship()




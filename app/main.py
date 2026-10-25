from __future__ import annotations

import csv
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import StringIO
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.config import get_settings
from app.configuration_api import router as configuration_router
from app.db import create_schema, get_engine, get_session
from app.errors import APIError
from app.models import (
    AuditEvent,
    AuthSession,
    CalculationSnapshot,
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
    ReworkOrder,
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
    utcnow,
)
from app.schemas import (
    AssignmentRequest,
    GenealogyActionRequest,
    LoginRequest,
    LocalPendingCorruptionRequest,
    OperationEventRequest,
    PendingResolveRequest,
    PlanCreateRequest,
    QCInspectionRequest,
    QualityAuditRequest,
    QualityDecisionRequest,
    ReworkOrderRequest,
    StandardCreateRequest,
    TimeEntryRequest,
    WorkSessionRequest,
)
from app.security import (
    CAPABILITIES_BY_ROLE,
    AuthContext,
    create_auth_session,
    get_auth_context,
    require_capability,
    require_csrf,
    require_csrf_capability,
    token_hash,
    verify_password,
)
from app.seed import DEMO_PASSWORD, seed_demo, upgrade_demo_foreman_scope
from app.services import (
    calculation_input_hash,
    calculate_row_metrics,
    calculate_shift,
    canonical_payload_hash,
    decimal_string,
    json_ready,
    latest_approved_plan,
    record_audit,
)

API = "/api/v1"

QC_DEFECT_REASONS: dict[str, str] = {
    "DEMO-JOINT": "ДЕМО · соединение или пайка",
    "DEMO-ASSEMBLY": "ДЕМО · сборка",
    "DEMO-COMPONENT": "ДЕМО · компонент",
    "DEMO-OTHER": "ДЕМО · другое",
}


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", str(uuid4()))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _page(items: list[dict], total: int, limit: int, offset: int) -> dict:
    next_cursor = str(offset + limit) if offset + limit < total else None
    return {"items": items, "total": total, "next_cursor": next_cursor}


def _user_payload(db: Session, context: AuthContext) -> dict:
    roles = list(db.scalars(select(UserRole).where(UserRole.user_id == context.user.id)))
    return {
        "id": context.user.id,
        "username": context.user.username,
        "display_name": context.user.display_name,
        "employee_id": context.user.employee_id,
        "roles": [{"name": role.role, "row_id": role.row_id} for role in roles],
        "scopes": {"row_ids": list(context.row_ids)},
        "capabilities": list(context.capabilities),
        "csrf_token": context.auth_session.csrf_token,
    }


def _row_payload(row: ProductionRow) -> dict:
    return {"id": row.id, "code": row.code, "name": row.name, "category": row.category, "sort_order": row.sort_order}


def _event_payload(event: OperationEvent) -> dict:
    return {
        "id": event.id,
        "status": event.status,
        "code": event.code,
        "server_received_at": event.server_received_at.isoformat(),
        "entity_id": event.entity_id,
        "route_step_id": event.route_step_id,
        "attempt_type": event.attempt_type,
        "attempt_no": event.attempt_no,
        "outcome": event.outcome,
    }


def _qc_inspection_payload(db: Session, decision: QualityDecision) -> dict:
    event = db.get(OperationEvent, decision.operation_event_id)
    entity = db.get(TrackedEntity, decision.entity_id)
    if event is None or entity is None:
        raise APIError(500, "QC_INSPECTION_INVARIANT_BROKEN", "Проверка ОТК не связана с событием или QR")
    work_session = db.get(WorkSession, event.work_session_id)
    row = db.get(ProductionRow, work_session.row_id) if work_session is not None else None
    step = db.get(RouteStep, event.route_step_id)
    is_corrected = db.scalar(select(func.count()).select_from(OperationEvent).where(
        OperationEvent.correction_of_id == event.id,
        OperationEvent.status == "ACCEPTED",
    )) > 0
    return {
        "event_id": event.id,
        "decision_id": decision.id,
        "subject_qr": entity.qr_code,
        "decision": decision.decision,
        "defect_code": decision.defect_code,
        "defect_label": QC_DEFECT_REASONS.get(decision.defect_code) if decision.defect_code else None,
        "attempt_type": event.attempt_type,
        "mode": "REINSPECTION" if event.attempt_type == "REWORK" else "FIRST_PASS",
        "corrected": is_corrected,
        "display_status": "CORRECTED" if is_corrected else event.status,
        "row": {"id": row.id, "code": row.code, "name": row.name} if row is not None else None,
        "route_step": {"id": step.id, "code": step.code, "name": step.name} if step is not None else None,
        "server_received_at": event.server_received_at.isoformat(),
        "created_at": decision.created_at.isoformat(),
    }


def _qc_inspection_response(db: Session, decision: QualityDecision, *, duplicate: bool) -> dict:
    inspection = _qc_inspection_payload(db, decision)
    return {
        "inspection_id": decision.request_id,
        "status": "ACCEPTED",
        "accepted": True,
        "terminal": True,
        "retryable": False,
        "duplicate": duplicate,
        "server_received_at": inspection["server_received_at"],
        "inspection": inspection,
        "message": "Проверка ОТК сохранена сервером",
    }


def _qc_replay_after_conflict(
    db: Session,
    inspection_id: str,
    actor_user_id: str,
    body_hash: str,
) -> dict | None:
    decision = db.scalar(select(QualityDecision).where(QualityDecision.request_id == inspection_id))
    if decision is None:
        return None
    if decision.inspector_user_id != actor_user_id:
        raise APIError(403, "QC_INSPECTION_OWNER_MISMATCH", "Идентификатор проверки принадлежит другому контролёру")
    receipt = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "QC_INSPECTION_RECORDED",
            AuditEvent.object_type == "quality_decision",
            AuditEvent.object_id == decision.id,
        ).order_by(AuditEvent.created_at.desc())
    )
    if receipt is None or (receipt.after or {}).get("payload_hash") != body_hash:
        raise APIError(409, "QC_INSPECTION_PAYLOAD_MISMATCH", "UUID проверки уже использован с другим содержимым")
    return _qc_inspection_response(db, decision, duplicate=True)


def _latest_effective_quality_decision(db: Session, entity_id: str) -> QualityDecision | None:
    correction = aliased(OperationEvent)
    return db.scalar(
        select(QualityDecision)
        .join(OperationEvent, OperationEvent.id == QualityDecision.operation_event_id)
        .where(
            QualityDecision.entity_id == entity_id,
            OperationEvent.status == "ACCEPTED",
            OperationEvent.event_type == "COMPLETE",
            OperationEvent.correction_of_id.is_(None),
            ~select(correction.id).where(
                correction.correction_of_id == OperationEvent.id,
                correction.status == "ACCEPTED",
            ).exists(),
        )
        .order_by(QualityDecision.created_at.desc(), QualityDecision.id.desc())
    )


def create_app(*, auto_seed: bool = True) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        create_schema()
        if auto_seed:
            with Session(get_engine()) as db:
                seed_demo(db)
                upgrade_demo_foreman_scope(db)
        yield

    app = FastAPI(title=settings.app_name, version="0.1-demo", docs_url="/docs", redoc_url=None, lifespan=lifespan)
    app.include_router(configuration_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        request.state.trace_id = request.headers.get("X-Request-ID") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.trace_id
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        event_id = getattr(request.state, "operation_event_id", None)
        inspection_id = getattr(request.state, "qc_inspection_id", None)
        terminal = bool(event_id) and exc.status_code < 500 and exc.status_code != 401 and exc.code != "EVENT_OWNER_MISMATCH"
        content = {"error": {"code": exc.code, "message": exc.message, "field_errors": exc.field_errors, "trace_id": _trace_id(request)}}
        if event_id:
            content["submission"] = {
                "event_id": event_id,
                "status": "REJECTED_TERMINAL" if terminal else "UNRESOLVED",
                "code": exc.code,
                "message": exc.message,
                "accepted": False,
                "terminal": terminal,
                "retryable": not terminal,
                "next_steps": ["FIX_AND_RESCAN"] if terminal else ["REAUTH_OR_FOREMAN_REVIEW"],
            }
        if inspection_id:
            inspection_terminal = (
                exc.status_code < 500
                and exc.status_code != 401
                and exc.code not in {
                    "QC_INSPECTION_OWNER_MISMATCH",
                    "QC_INSPECTION_IN_PROGRESS",
                    "CONCURRENT_QC_INSPECTION",
                    "QC_INSPECTION_PAYLOAD_MISMATCH",
                }
            )
            content["submission"] = {
                "inspection_id": inspection_id,
                "status": "REJECTED_TERMINAL" if inspection_terminal else "UNRESOLVED",
                "code": exc.code,
                "message": exc.message,
                "accepted": False,
                "terminal": inspection_terminal,
                "retryable": not inspection_terminal,
                "next_steps": ["FIX_AND_RESCAN"] if inspection_terminal else ["RETRY_SAME_UUID"],
            }
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(x) for x in error["loc"]), "message": error["msg"]} for error in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": "Проверьте поля запроса", "field_errors": fields, "trace_id": _trace_id(request)}},
        )

    @app.get(f"{API}/health/live")
    def live() -> dict:
        return {"status": "ok", "mode": "DEMO"}

    @app.get(f"{API}/health/ready")
    def ready(db: Session = Depends(get_session)) -> dict:
        db.scalar(select(func.count()).select_from(User))
        return {"status": "ready", "database": db.bind.dialect.name if db.bind else "unknown"}

    @app.post(f"{API}/auth/login")
    def login(payload: LoginRequest, response: Response, db: Session = Depends(get_session)) -> dict:
        user = db.scalar(select(User).where(User.username == payload.username))
        if user is None or not user.is_active or not verify_password(user.password_hash, payload.password):
            raise APIError(401, "INVALID_CREDENTIALS", "Неверное имя пользователя или пароль")
        auth_session, raw_token = create_auth_session(db, user)
        db.commit()
        response.set_cookie(
            settings.session_cookie_name,
            raw_token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=settings.session_hours * 3600,
            path="/",
        )
        roles = list(db.scalars(select(UserRole).where(UserRole.user_id == user.id)))
        role_names = tuple(sorted({role.role for role in roles}))
        row_ids = tuple(sorted({role.row_id for role in roles if role.row_id}))
        caps = tuple(sorted(set().union(*(CAPABILITIES_BY_ROLE.get(role, set()) for role in role_names))))
        return {"user": _user_payload(db, AuthContext(user, auth_session, role_names, row_ids, caps))}

    @app.get(f"{API}/auth/me")
    def me(context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_session)) -> dict:
        return {"user": _user_payload(db, context)}

    @app.post(f"{API}/auth/logout", status_code=204)
    def logout(response: Response, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_session)) -> Response:
        context.auth_session.revoked_at = utcnow()
        db.commit()
        response.delete_cookie(settings.session_cookie_name, path="/")
        response.status_code = 204
        return response

    @app.get(f"{API}/bootstrap")
    def bootstrap(context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_session)) -> dict:
        shift = db.scalar(select(Shift).where(Shift.status == "RUNNING").order_by(Shift.starts_at.desc()))
        if shift is None:
            raise APIError(404, "ACTIVE_SHIFT_NOT_FOUND", "Активная смена не найдена")
        rows = list(db.scalars(select(ProductionRow).order_by(ProductionRow.sort_order)))
        stations = list(db.scalars(select(Workstation).order_by(Workstation.code)))
        route = db.scalar(select(RouteVersion).where(RouteVersion.status == "APPROVED").order_by(RouteVersion.version.desc()))
        steps = list(db.scalars(select(RouteStep).where(RouteStep.route_version_id == route.id).order_by(RouteStep.sequence))) if route else []
        return {
            "active_shift": {
                "id": shift.id, "code": shift.code, "production_date": shift.production_date,
                "status": shift.status, "approval_status": shift.approval_status,
                "maturity_state": shift.maturity_state, "demo_business_date": True,
            },
            "rows": [_row_payload(row) for row in rows],
            "workstations": [{"id": item.id, "code": item.code, "name": item.name, "row_id": item.row_id} for item in stations],
            "route_steps": [{
                "id": step.id, "code": step.code, "name": step.name, "sequence": step.sequence,
                "row_id": step.row_id, "entity_type": step.entity_type, "allows_rework": step.allows_rework,
            } for step in steps],
            "capabilities": list(context.capabilities),
            "scopes": {"row_ids": list(context.row_ids)},
            "sample_qr": ["DEMO-WIP-004", "DEMO-WIP-005", "DEMO-COMP-FC-001", "DEMO-FINAL-001"],
            "version": "DEMO-DATA-V1",
            "updated_at": shift.updated_at.isoformat(),
            "synthetic": True,
        }

    @app.get(f"{API}/me/shift-activity")
    def my_shift_activity(
        limit: int = Query(default=10, ge=1, le=10),
        context: AuthContext = Depends(require_capability("scan")),
        db: Session = Depends(get_session),
    ) -> dict:
        shift = db.scalar(select(Shift).where(Shift.status == "RUNNING").order_by(Shift.starts_at.desc()))
        if shift is None:
            raise APIError(404, "ACTIVE_SHIFT_NOT_FOUND", "Активная смена не найдена")
        employee = db.get(Employee, context.user.employee_id) if context.user.employee_id else None
        if employee is None:
            raise APIError(409, "EMPLOYEE_CONTEXT_REQUIRED", "Для учёта личной активности нужен сотрудник")

        correction = aliased(OperationEvent)
        effective_completion = (
            OperationEvent.shift_id == shift.id,
            OperationEvent.user_id == context.user.id,
            OperationEvent.status == "ACCEPTED",
            OperationEvent.event_type == "COMPLETE",
            OperationEvent.correction_of_id.is_(None),
            ~select(correction.id).where(
                correction.correction_of_id == OperationEvent.id,
                correction.status == "ACCEPTED",
            ).exists(),
        )
        primary_completed_count = db.scalar(
            select(func.count()).select_from(OperationEvent).where(
                *effective_completion,
                OperationEvent.attempt_type == "PRIMARY",
            )
        ) or 0
        rework_completed_count = db.scalar(
            select(func.count()).select_from(OperationEvent).where(
                *effective_completion,
                OperationEvent.attempt_type == "REWORK",
            )
        ) or 0

        worker_primary = aliased(OperationEvent)
        corrected_primary_count = db.scalar(
            select(func.count(func.distinct(worker_primary.id)))
            .select_from(worker_primary)
            .join(OperationEvent, OperationEvent.correction_of_id == worker_primary.id)
            .where(
                worker_primary.shift_id == shift.id,
                worker_primary.user_id == context.user.id,
                worker_primary.status == "ACCEPTED",
                worker_primary.event_type == "COMPLETE",
                worker_primary.attempt_type == "PRIMARY",
                OperationEvent.status == "ACCEPTED",
            )
        ) or 0

        active_session = db.scalar(
            select(WorkSession)
            .join(ShiftAssignment, ShiftAssignment.id == WorkSession.assignment_id)
            .where(
                WorkSession.user_id == context.user.id,
                WorkSession.shift_id == shift.id,
                WorkSession.ended_at.is_(None),
                ShiftAssignment.status == "ACTIVE",
            )
            .order_by(WorkSession.started_at.desc(), WorkSession.id.desc())
        )
        session_context = None
        if active_session is not None:
            row = db.get(ProductionRow, active_session.row_id)
            step = db.get(RouteStep, active_session.route_step_id)
            if row is not None and step is not None:
                session_context = {
                    "work_session_id": active_session.id,
                    "row": {"id": row.id, "code": row.code, "name": row.name},
                    "route_step": {"id": step.id, "code": step.code, "name": step.name},
                }

        recent = list(db.scalars(
            select(OperationEvent)
            .where(
                OperationEvent.shift_id == shift.id,
                OperationEvent.user_id == context.user.id,
                OperationEvent.event_type == "COMPLETE",
            )
            .order_by(OperationEvent.server_received_at.desc(), OperationEvent.id.desc())
            .limit(limit)
        ))
        recent_ids = [event.id for event in recent]
        corrected_ids = set(db.scalars(
            select(OperationEvent.correction_of_id).where(
                OperationEvent.correction_of_id.in_(recent_ids),
                OperationEvent.status == "ACCEPTED",
            )
        )) if recent_ids else set()

        recent_events = []
        for event in recent:
            work_session = db.get(WorkSession, event.work_session_id)
            row = db.get(ProductionRow, work_session.row_id) if work_session is not None else None
            step = db.get(RouteStep, event.route_step_id)
            entity = db.get(TrackedEntity, event.entity_id)
            is_corrected = event.id in corrected_ids
            if is_corrected:
                display_status = "CORRECTED"
            elif event.attempt_type == "REWORK" and event.status == "ACCEPTED":
                display_status = "REWORK"
            else:
                display_status = event.status
            recent_events.append({
                "id": event.id,
                "event_id": event.id,
                "subject_qr": entity.qr_code if entity is not None else None,
                "attempt_type": event.attempt_type,
                "event_type": event.event_type,
                "status": event.status,
                "display_status": display_status,
                "code": event.code,
                "outcome": event.outcome,
                "server_received_at": event.server_received_at.isoformat(),
                "corrected": is_corrected,
                "row": {"id": row.id, "code": row.code, "name": row.name} if row is not None else None,
                "route_step": {"id": step.id, "code": step.code, "name": step.name} if step is not None else None,
            })

        return {
            "shift": {"id": shift.id, "code": shift.code, "production_date": shift.production_date},
            "employee": {"id": employee.id, "display_name": employee.display_name},
            "context": session_context,
            "primary_completed": primary_completed_count,
            "rework_completed": rework_completed_count,
            "corrected_primary": corrected_primary_count,
            "recent_events": recent_events,
            "note": "Счётчики операций сотрудника не являются количеством готовых изделий или персональным KPI.",
        }

    @app.get(f"{API}/me/foreman-shift-summary")
    def my_foreman_shift_summary(
        limit: int = Query(default=10, ge=1, le=50),
        context: AuthContext = Depends(require_capability("view_reports")),
        db: Session = Depends(get_session),
    ) -> dict:
        if "FOREMAN" not in context.role_names:
            raise APIError(403, "FOREMAN_ROLE_REQUIRED", "Экран ряда доступен только бригадиру")
        shift = db.scalar(select(Shift).where(Shift.status == "RUNNING").order_by(Shift.starts_at.desc()))
        if shift is None:
            raise APIError(404, "ACTIVE_SHIFT_NOT_FOUND", "Активная смена не найдена")

        scoped_rows = set(db.scalars(select(UserRole.row_id).where(
            UserRole.user_id == context.user.id,
            UserRole.role == "FOREMAN",
            UserRole.row_id.is_not(None),
        )))
        if len(scoped_rows) > 1:
            raise APIError(409, "FOREMAN_ROW_SCOPE_AMBIGUOUS", "Для бригадира задано несколько рядов; нужен один явный scope")
        if scoped_rows:
            row_id = next(iter(scoped_rows))
        else:
            if context.user.employee_id is None:
                raise APIError(409, "FOREMAN_ROW_SCOPE_MISSING", "Для бригадира не задан ряд")
            assignment_rows = set(db.scalars(select(ShiftAssignment.row_id).where(
                ShiftAssignment.shift_id == shift.id,
                ShiftAssignment.employee_id == context.user.employee_id,
                ShiftAssignment.status == "ACTIVE",
            )))
            if not assignment_rows:
                raise APIError(409, "FOREMAN_ROW_SCOPE_MISSING", "Для бригадира не задан ряд и нет активного назначения")
            if len(assignment_rows) > 1:
                raise APIError(409, "FOREMAN_ROW_SCOPE_AMBIGUOUS", "Активные назначения бригадира относятся к нескольким рядам")
            row_id = next(iter(assignment_rows))
        row = db.get(ProductionRow, row_id)
        if row is None:
            raise APIError(409, "FOREMAN_ROW_SCOPE_INVALID", "Ряд из scope бригадира не найден")

        assignments = list(db.scalars(
            select(ShiftAssignment).where(
                ShiftAssignment.shift_id == shift.id,
                ShiftAssignment.row_id == row.id,
            ).order_by(ShiftAssignment.starts_at, ShiftAssignment.created_at)
        ))
        roster = []
        for assignment in assignments:
            employee = db.get(Employee, assignment.employee_id)
            workstation = db.get(Workstation, assignment.workstation_id)
            step = db.get(RouteStep, assignment.route_step_id)
            roster.append({
                "assignment_id": assignment.id,
                "employee": {
                    "id": employee.id,
                    "display_name": employee.display_name,
                    "personnel_no": employee.code,
                    "status": employee.status,
                } if employee is not None else None,
                "workstation": {"id": workstation.id, "name": workstation.name} if workstation is not None else None,
                "route_step": {"id": step.id, "name": step.name} if step is not None else None,
                "assignment_status": assignment.status,
                "starts_at": assignment.starts_at.isoformat(),
                "ends_at": assignment.ends_at.isoformat(),
            })

        correction = aliased(OperationEvent)
        row_completion = (
            OperationEvent.shift_id == shift.id,
            OperationEvent.status == "ACCEPTED",
            OperationEvent.event_type == "COMPLETE",
            OperationEvent.correction_of_id.is_(None),
            WorkSession.row_id == row.id,
            ~select(correction.id).where(
                correction.correction_of_id == OperationEvent.id,
                correction.status == "ACCEPTED",
            ).exists(),
        )
        primary_completed = db.scalar(
            select(func.count()).select_from(OperationEvent)
            .join(WorkSession, WorkSession.id == OperationEvent.work_session_id)
            .where(*row_completion, OperationEvent.attempt_type == "PRIMARY")
        ) or 0
        rework_completed = db.scalar(
            select(func.count()).select_from(OperationEvent)
            .join(WorkSession, WorkSession.id == OperationEvent.work_session_id)
            .where(*row_completion, OperationEvent.attempt_type == "REWORK")
        ) or 0

        problems: list[dict] = []
        needs_review = list(db.scalars(
            select(OperationEvent)
            .join(WorkSession, WorkSession.id == OperationEvent.work_session_id)
            .where(
                OperationEvent.shift_id == shift.id,
                OperationEvent.status == "NEEDS_REVIEW",
                WorkSession.row_id == row.id,
            )
            .order_by(OperationEvent.server_received_at.desc(), OperationEvent.id.desc())
            .limit(limit)
        ))
        for event in needs_review:
            entity = db.get(TrackedEntity, event.entity_id)
            step = db.get(RouteStep, event.route_step_id)
            worker = db.get(User, event.user_id)
            problems.append({
                "id": event.id,
                "kind": "NEEDS_REVIEW",
                "code": event.code,
                "qr": entity.qr_code if entity is not None else None,
                "operation": {"id": step.id, "name": step.name} if step is not None else None,
                "worker": {"id": worker.id, "display_name": worker.display_name} if worker is not None else None,
                "occurred_at": event.server_received_at.isoformat(),
                "status": event.status,
                "message": event.reason or "Сканирование ожидает проверки",
                "allowed_actions": [],
            })

        rejection_rows = list(db.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "OPERATION_SCAN_REJECTED",
                AuditEvent.object_type == f"scan_rejection:{row.id}",
            ).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        ))
        seen_rejections: set[str] = set()
        for issue in rejection_rows:
            data = issue.after or {}
            if data.get("shift_id") != shift.id or issue.object_id in seen_rejections:
                continue
            seen_rejections.add(issue.object_id)
            step = db.get(RouteStep, data.get("route_step_id")) if data.get("route_step_id") else None
            worker = db.get(User, issue.actor_user_id) if issue.actor_user_id else None
            problems.append({
                "id": issue.id,
                "kind": "SCAN_REJECTED",
                "code": data.get("code", "SCAN_REJECTED"),
                "qr": data.get("subject_qr"),
                "operation": {"id": step.id, "name": step.name} if step is not None else None,
                "worker": {"id": worker.id, "display_name": worker.display_name} if worker is not None else None,
                "occurred_at": issue.created_at.isoformat(),
                "status": "REJECTED_TERMINAL",
                "message": data.get("message", "Сканирование отклонено сервером"),
                "allowed_actions": [],
            })
        problems.sort(key=lambda item: (item["occurred_at"], item["id"]), reverse=True)
        problems = problems[:limit]

        reworks: list[dict] = []
        orders = list(db.scalars(
            select(ReworkOrder)
            .join(QualityDecision, QualityDecision.id == ReworkOrder.quality_decision_id)
            .where(QualityDecision.shift_id == shift.id)
            .order_by(ReworkOrder.created_at.desc(), ReworkOrder.id.desc())
        ))
        for order in orders:
            step = db.get(RouteStep, order.requested_route_step_id)
            belongs_to_row = step is not None and step.row_id == row.id
            if step is not None and step.row_id is None:
                next_order_at = db.scalar(select(func.min(ReworkOrder.created_at)).where(
                    ReworkOrder.entity_id == order.entity_id,
                    ReworkOrder.requested_route_step_id == order.requested_route_step_id,
                    ReworkOrder.created_at > order.created_at,
                ))
                rework_correction = aliased(OperationEvent)
                actual_query = (
                    select(OperationEvent)
                    .join(WorkSession, WorkSession.id == OperationEvent.work_session_id)
                    .where(
                        OperationEvent.entity_id == order.entity_id,
                        OperationEvent.route_step_id == order.requested_route_step_id,
                        OperationEvent.shift_id == shift.id,
                        OperationEvent.status == "ACCEPTED",
                        OperationEvent.event_type == "COMPLETE",
                        OperationEvent.attempt_type == "REWORK",
                        OperationEvent.correction_of_id.is_(None),
                        OperationEvent.server_received_at >= order.created_at,
                        WorkSession.row_id == row.id,
                        ~select(rework_correction.id).where(
                            rework_correction.correction_of_id == OperationEvent.id,
                            rework_correction.status == "ACCEPTED",
                        ).exists(),
                    )
                    .order_by(OperationEvent.server_received_at.desc(), OperationEvent.id.desc())
                )
                if next_order_at is not None:
                    actual_query = actual_query.where(OperationEvent.server_received_at < next_order_at)
                actual_event = db.scalar(actual_query)
                belongs_to_row = actual_event is not None
            if not belongs_to_row:
                continue
            entity = db.get(TrackedEntity, order.entity_id)
            reworks.append({
                "id": order.id,
                "qr": entity.qr_code if entity is not None else None,
                "reason": order.reason,
                "requested_route_step": {"id": step.id, "name": step.name} if step is not None else None,
                "status": order.status,
                "created_at": order.created_at.isoformat(),
                "allowed_actions": [],
            })
            if len(reworks) >= limit:
                break

        return {
            "shift": {"id": shift.id, "code": shift.code, "production_date": shift.production_date},
            "row": {"id": row.id, "code": row.code, "name": row.name, "category": row.category},
            "roster": roster,
            "primary_completed": primary_completed,
            "rework_completed": rework_completed,
            "problems": problems,
            "reworks": reworks,
            "note": "Состав отражает назначения, а не присутствие онлайн; счётчики — операции ряда, не готовые изделия и не персональный KPI.",
        }

    @app.get(f"{API}/employees")
    def employees(
        context: AuthContext = Depends(require_capability("manage_assignments")),
        db: Session = Depends(get_session),
    ) -> dict:
        items = list(db.scalars(select(Employee).order_by(Employee.display_name)))
        return {"items": [{"id": item.id, "display_name": item.display_name, "personnel_no": item.code, "status": item.status} for item in items], "total": len(items), "next_cursor": None}

    @app.get(f"{API}/dashboard")
    def dashboard(context: AuthContext = Depends(require_capability("view_reports")), db: Session = Depends(get_session)) -> dict:
        shift = db.scalar(select(Shift).where(Shift.status == "RUNNING").order_by(Shift.starts_at.desc()))
        if shift is None:
            raise APIError(404, "ACTIVE_SHIFT_NOT_FOUND", "Активная смена не найдена")
        metrics = calculate_shift(db, shift.id)
        rows = []
        row_metrics = []
        for row in db.scalars(select(ProductionRow).order_by(ProductionRow.sort_order)):
            facts = db.scalar(
                select(func.count()).select_from(OperationEvent)
                .join(WorkSession, WorkSession.id == OperationEvent.work_session_id)
                .where(OperationEvent.shift_id == shift.id, WorkSession.row_id == row.id, OperationEvent.status == "ACCEPTED")
            ) or 0
            row_metric = calculate_row_metrics(db, shift.id, row.id)
            row_metrics.append(row_metric)
            rows.append({**_row_payload(row), "accepted_operations": facts, "metrics": row_metric})
        return {"shift": {"id": shift.id, "code": shift.code}, "rows": rows, "row_metrics": row_metrics, "calculation": metrics, "synthetic": True}

    @app.get(f"{API}/shifts")
    def shifts(context: AuthContext = Depends(require_capability("view_reports")), db: Session = Depends(get_session)) -> dict:
        rows = list(db.scalars(select(Shift).order_by(Shift.starts_at.desc())))
        return _page([{
            "id": item.id, "code": item.code, "production_date": item.production_date,
            "starts_at": item.starts_at.isoformat(), "ends_at": item.ends_at.isoformat(),
            "status": item.status, "approval_status": item.approval_status,
            "maturity_state": item.maturity_state, "version": item.version,
        } for item in rows], len(rows), len(rows) or 1, 0)

    @app.get(f"{API}/work-sessions")
    def list_work_sessions(context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_session)) -> dict:
        query = select(WorkSession).order_by(WorkSession.started_at.desc())
        if "admin" not in context.capabilities and "manage_assignments" not in context.capabilities:
            query = query.where(WorkSession.user_id == context.user.id)
        items = list(db.scalars(query))
        return _page([{
            "id": item.id, "user_id": item.user_id, "employee_id": item.employee_id, "shift_id": item.shift_id,
            "row_id": item.row_id, "workstation_id": item.workstation_id, "route_step_id": item.route_step_id,
            "assignment_id": item.assignment_id, "started_at": item.started_at.isoformat(),
            "ended_at": item.ended_at.isoformat() if item.ended_at else None,
        } for item in items], len(items), len(items) or 1, 0)

    @app.post(f"{API}/work-sessions", status_code=201)
    def start_work_session(
        payload: WorkSessionRequest,
        context: AuthContext = Depends(require_csrf_capability("scan")),
        db: Session = Depends(get_session),
    ) -> dict:
        assignment = db.scalar(select(ShiftAssignment).where(
            ShiftAssignment.shift_id == payload.shift_id,
            ShiftAssignment.employee_id == context.user.employee_id,
            ShiftAssignment.row_id == payload.row_id,
            ShiftAssignment.workstation_id == payload.workstation_id,
            ShiftAssignment.route_step_id == payload.route_step_id,
            ShiftAssignment.status == "ACTIVE",
        ))
        if assignment is None:
            raise APIError(403, "ASSIGNMENT_SCOPE_MISMATCH", "Нет подходящего назначения сотрудника")
        session = WorkSession(
            user_id=context.user.id, employee_id=context.user.employee_id, shift_id=payload.shift_id,
            row_id=payload.row_id, workstation_id=payload.workstation_id,
            route_step_id=payload.route_step_id, assignment_id=assignment.id,
        )
        db.add(session)
        db.flush()
        record_audit(db, actor_user_id=context.user.id, action="WORK_SESSION_STARTED", object_type="work_session", object_id=session.id, trace_id=str(uuid4()), after={"assignment_id": assignment.id})
        db.commit()
        return {"id": session.id, "assignment_id": assignment.id, "started_at": session.started_at.isoformat()}

    @app.delete(f"{API}/work-sessions/{{session_id}}", status_code=204)
    def end_work_session(session_id: str, context: AuthContext = Depends(require_csrf_capability("scan")), db: Session = Depends(get_session)) -> Response:
        work_session = db.get(WorkSession, session_id)
        if work_session is None:
            raise APIError(404, "WORK_SESSION_NOT_FOUND", "Рабочая сессия не найдена")
        if work_session.user_id != context.user.id:
            raise APIError(403, "WORK_SESSION_OWNER_MISMATCH", "Нельзя завершить чужую рабочую сессию")
        work_session.ended_at = utcnow()
        db.commit()
        return Response(status_code=204)

    @app.post(f"{API}/operation-events")
    def scan_operation(
        payload: OperationEventRequest,
        request: Request,
        context: AuthContext = Depends(require_csrf_capability("scan")),
        db: Session = Depends(get_session),
    ) -> dict:
        request.state.operation_event_id = payload.event_id
        body_hash = canonical_payload_hash(payload.model_dump(mode="json"))
        prior = db.get(OperationEvent, payload.event_id)
        if prior is not None:
            if prior.user_id != context.user.id:
                raise APIError(403, "EVENT_OWNER_MISMATCH", "Идентификатор события принадлежит другому оператору")
            if prior.payload_hash != body_hash:
                raise APIError(409, "IDEMPOTENCY_PAYLOAD_MISMATCH", "UUID уже использован с другим содержимым")
            return {**_event_payload(prior), "accepted": True, "terminal": True, "duplicate": True, "retryable": False, "review_id": None, "next_steps": []}

        rejected_receipt = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "OPERATION_SCAN_REJECTED",
                AuditEvent.object_id == payload.event_id,
            ).order_by(AuditEvent.created_at.desc())
        )
        if rejected_receipt is not None:
            rejected_data = rejected_receipt.after or {}
            if rejected_receipt.actor_user_id != context.user.id:
                raise APIError(403, "EVENT_OWNER_MISMATCH", "Идентификатор события принадлежит другому оператору")
            if rejected_data.get("payload_hash") != body_hash:
                raise APIError(409, "IDEMPOTENCY_PAYLOAD_MISMATCH", "UUID уже использован с другим содержимым")
            raise APIError(
                int(rejected_data.get("http_status", 409)),
                str(rejected_data.get("code", "SCAN_REJECTED")),
                str(rejected_data.get("message", "Сканирование было отклонено сервером")),
            )

        work_session = db.get(WorkSession, payload.work_session_id)
        if work_session is None:
            raise APIError(404, "WORK_SESSION_NOT_FOUND", "Рабочая сессия не найдена")
        if work_session.user_id != context.user.id:
            raise APIError(403, "WORK_SESSION_OWNER_MISMATCH", "Рабочая сессия принадлежит другому оператору")
        if work_session.ended_at is not None:
            raise APIError(409, "WORK_SESSION_ENDED", "Рабочая сессия уже завершена")
        shift = db.get(Shift, work_session.shift_id)
        if shift is None or shift.status != "RUNNING" or shift.approval_status == "APPROVED":
            raise APIError(409, "SHIFT_NOT_MUTABLE", "Смена закрыта или уже утверждена; новые события запрещены")

        def reject_scan(status_code: int, code: str, message: str, *, entity_id: str | None = None) -> None:
            """Persist a definite owned-session rejection without creating production fact."""
            receipt = db.scalar(select(AuditEvent).where(
                AuditEvent.action == "OPERATION_SCAN_REJECTED",
                AuditEvent.object_id == payload.event_id,
            ))
            if receipt is None:
                record_audit(
                    db,
                    actor_user_id=context.user.id,
                    action="OPERATION_SCAN_REJECTED",
                    object_type=f"scan_rejection:{work_session.row_id}",
                    object_id=payload.event_id,
                    trace_id=_trace_id(request),
                    after={
                        "payload_hash": body_hash,
                        "http_status": status_code,
                        "code": code,
                        "message": message,
                        "status": "REJECTED_TERMINAL",
                        "shift_id": work_session.shift_id,
                        "row_id": work_session.row_id,
                        "work_session_id": work_session.id,
                        "route_step_id": work_session.route_step_id,
                        "entity_id": entity_id,
                        "subject_qr": payload.subject_qr,
                    },
                )
                db.commit()
            raise APIError(status_code, code, message)

        assignment = db.get(ShiftAssignment, work_session.assignment_id)
        if (
            assignment is None
            or assignment.status != "ACTIVE"
            or assignment.employee_id != context.user.employee_id
            or assignment.shift_id != work_session.shift_id
            or assignment.row_id != work_session.row_id
            or assignment.workstation_id != work_session.workstation_id
            or assignment.route_step_id != work_session.route_step_id
        ):
            reject_scan(409, "WORK_ASSIGNMENT_INACTIVE", "Назначение изменено или завершено; откройте новую рабочую сессию")

        entity = db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == payload.subject_qr))
        if entity is None:
            reject_scan(404, "ENTITY_NOT_FOUND", "QR не зарегистрирован")
        if entity.status in {"SCRAPPED", "RETIRED", "FINISHED"}:
            reject_scan(409, "ENTITY_NOT_SCANNABLE", "Списанная, архивная или завершённая сущность не принимает операции", entity_id=entity.id)
        step = db.get(RouteStep, work_session.route_step_id)
        row = db.get(ProductionRow, work_session.row_id)
        if step is None or row is None:
            reject_scan(409, "WORK_CONTEXT_INVALID", "Контекст рабочей сессии повреждён", entity_id=entity.id)
        if entity.route_version_id != step.route_version_id:
            reject_scan(409, "ROUTE_VERSION_MISMATCH", "Операция рабочей сессии относится к другой версии маршрута изделия", entity_id=entity.id)
        if entity.entity_type != step.entity_type:
            reject_scan(409, "ENTITY_TYPE_MISMATCH", "Тип QR не соответствует типу сущности операции", entity_id=entity.id)
        allowed = step.row_id == row.id or (step.row_id is None and row.category == "ASSEMBLY")
        if not allowed:
            reject_scan(403, "ROW_OPERATION_SCOPE_MISMATCH", "Операция не разрешена на этом ряду", entity_id=entity.id)

        semantic = db.scalar(select(OperationEvent).where(
            OperationEvent.entity_id == entity.id,
            OperationEvent.route_step_id == step.id,
            OperationEvent.attempt_no == payload.attempt_no,
            OperationEvent.attempt_type == payload.attempt_type,
            OperationEvent.event_type == payload.event_type,
        ))
        if semantic is not None:
            return {**_event_payload(semantic), "accepted": False, "terminal": True, "duplicate": True, "code": "SEMANTIC_DUPLICATE", "retryable": False, "review_id": None, "next_steps": []}

        projection = db.scalar(select(OperationProjection).where(OperationProjection.entity_id == entity.id))
        rework_order = db.scalar(select(ReworkOrder).where(ReworkOrder.entity_id == entity.id, ReworkOrder.status.in_(["OPEN", "READY_FOR_QC"])).order_by(ReworkOrder.created_at.desc()))
        if payload.attempt_type == "PRIMARY":
            expected = 1 if projection is None else projection.route_position + 1
            if step.sequence != expected:
                reject_scan(409, "ROUTE_VIOLATION", f"Ожидалась позиция маршрута {expected}, получена {step.sequence}", entity_id=entity.id)
        else:
            valid_rework_step = rework_order is not None and (
                (rework_order.status == "OPEN" and rework_order.requested_route_step_id == step.id)
                or (rework_order.status == "READY_FOR_QC" and row.category == "QC")
            )
            if not valid_rework_step:
                reject_scan(409, "REWORK_NOT_AUTHORIZED", "Для операции нет открытого разрешения rework", entity_id=entity.id)

        plan = latest_approved_plan(db, work_session.shift_id)
        plan_line = db.scalar(select(PlanLine).where(
            PlanLine.plan_version_id == plan.id,
            PlanLine.route_step_id == step.id,
            or_(PlanLine.row_id == work_session.row_id, PlanLine.row_id.is_(None)),
        ).order_by(PlanLine.row_id.desc()))
        event = OperationEvent(
            id=payload.event_id, payload_hash=body_hash, shift_id=work_session.shift_id,
            work_session_id=work_session.id, entity_id=entity.id, route_step_id=step.id,
            plan_line_id=plan_line.id if plan_line else None, user_id=context.user.id,
            attempt_no=payload.attempt_no, attempt_type=payload.attempt_type,
            event_type=payload.event_type, outcome="COMPLETED", status="ACCEPTED", code="EVENT_ACCEPTED",
            occurred_at_device=payload.occurred_at_device,
        )
        db.add(event)
        db.flush()
        if projection is None:
            projection = OperationProjection(
                entity_id=entity.id, last_event_id=event.id, last_route_step_id=step.id,
                route_position=step.sequence, status="IN_PROGRESS", version=1,
            )
            db.add(projection)
        elif payload.attempt_type == "PRIMARY":
            projection.last_event_id = event.id
            projection.last_route_step_id = step.id
            projection.route_position = step.sequence
            projection.version += 1
        if rework_order is not None and payload.attempt_type == "REWORK":
            rework_order.status = "READY_FOR_QC" if rework_order.status == "OPEN" else "REINSPECTED"
        record_audit(db, actor_user_id=context.user.id, action="OPERATION_ACCEPTED", object_type="operation_event", object_id=event.id, trace_id=_trace_id(request), after=_event_payload(event))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise APIError(409, "CONCURRENT_DUPLICATE", "Операция уже принята параллельным запросом")
        return {**_event_payload(event), "accepted": True, "terminal": True, "duplicate": False, "retryable": False, "review_id": None, "next_steps": ["REFRESH_DASHBOARD"]}

    @app.get(f"{API}/operation-events/{{event_id}}/status")
    def operation_status(event_id: str, context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_session)) -> dict:
        event = db.get(OperationEvent, event_id)
        if event is None:
            return {"id": event_id, "status": "NOT_FOUND", "code": "EVENT_NOT_FOUND", "accepted": False, "terminal": False, "retryable": True, "next_steps": ["RETRY_SAME_UUID"]}
        if event.user_id != context.user.id and "resolve_pending" not in context.capabilities:
            raise APIError(403, "EVENT_OWNER_MISMATCH", "Статус чужого события недоступен")
        return {**_event_payload(event), "accepted": event.status == "ACCEPTED", "terminal": event.status in {"ACCEPTED", "CANCELLED"}, "retryable": False, "review_id": None, "next_steps": []}

    @app.post(f"{API}/operation-events/{{event_id}}/resolve")
    def resolve_event(event_id: str, payload: PendingResolveRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("resolve_pending")), db: Session = Depends(get_session)) -> dict:
        event = db.get(OperationEvent, event_id)
        if event is None:
            raise APIError(404, "EVENT_NOT_FOUND", "Событие не найдено")
        if event.status != "NEEDS_REVIEW":
            raise APIError(409, "EVENT_NOT_PENDING", "Принятое событие нельзя отменить через pending resolve")
        event.status = "CANCELLED"
        event.code = "CANCELLED_BY_FOREMAN"
        event.reason = payload.reason
        record_audit(db, actor_user_id=context.user.id, action="PENDING_CANCELLED", object_type="operation_event", object_id=event.id, trace_id=_trace_id(request), reason=payload.reason)
        db.commit()
        return _event_payload(event)

    @app.post(f"{API}/operation-events/resolve-local-corruption")
    def resolve_local_corruption(payload: LocalPendingCorruptionRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("resolve_pending")), db: Session = Depends(get_session)) -> dict:
        acknowledgement_id = str(uuid4())
        record_audit(
            db, actor_user_id=context.user.id, action="LOCAL_PENDING_DISCARDED",
            object_type="client_pending", object_id=acknowledgement_id, trace_id=_trace_id(request),
            after={"fingerprint": payload.fingerprint}, reason=payload.reason,
        )
        db.commit()
        return {"id": acknowledgement_id, "status": "CANCELLED", "code": "LOCAL_PENDING_DISCARDED", "retryable": False, "next_steps": ["CLEAR_LOCAL_PENDING"]}

    @app.get(f"{API}/entities/by-qr/{{qr_code}}")
    def entity_by_qr(qr_code: str, context: AuthContext = Depends(require_capability("read_entities")), db: Session = Depends(get_session)) -> dict:
        entity = db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == qr_code))
        if entity is None:
            raise APIError(404, "ENTITY_NOT_FOUND", "QR не зарегистрирован")
        return {"id": entity.id, "qr_code": entity.qr_code, "entity_type": entity.entity_type, "status": entity.status, "final_serial": entity.final_serial}

    @app.get(f"{API}/entities/{{entity_id}}/timeline")
    def entity_timeline(entity_id: str, context: AuthContext = Depends(require_capability("read_entities")), db: Session = Depends(get_session)) -> dict:
        entity = db.get(TrackedEntity, entity_id)
        if entity is None:
            raise APIError(404, "ENTITY_NOT_FOUND", "Сущность не найдена")
        events: list[dict] = []
        for event in db.scalars(select(OperationEvent).where(OperationEvent.entity_id == entity.id).order_by(OperationEvent.server_received_at)):
            events.append({"kind": "route", "at": event.server_received_at.isoformat(), **_event_payload(event)})
        links = list(db.scalars(select(GenealogyLink).where(or_(GenealogyLink.parent_entity_id == entity.id, GenealogyLink.child_entity_id == entity.id)).order_by(GenealogyLink.created_at)))
        for link in links:
            events.append({"kind": "genealogy", "at": link.created_at.isoformat(), "id": link.id, "action": link.action, "parent_entity_id": link.parent_entity_id, "child_entity_id": link.child_entity_id, "active": link.active, "ended_at": link.ended_at.isoformat() if link.ended_at else None})
        for decision in db.scalars(select(QualityDecision).where(QualityDecision.entity_id == entity.id).order_by(QualityDecision.created_at)):
            events.append({"kind": "quality", "at": decision.created_at.isoformat(), "id": decision.id, "decision": decision.decision, "defect_code": decision.defect_code})
        events.sort(key=lambda item: item["at"])
        return {"entity": {"id": entity.id, "qr_code": entity.qr_code, "entity_type": entity.entity_type, "status": entity.status}, "items": events, "total": len(events), "next_cursor": None}

    @app.post(f"{API}/genealogy/actions", status_code=201)
    def genealogy_action(payload: GenealogyActionRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("manage_genealogy")), db: Session = Depends(get_session)) -> dict:
        existing = db.scalar(select(GenealogyLink).where(GenealogyLink.request_id == payload.request_id))
        if existing:
            return {"id": existing.id, "action": existing.action, "active": existing.active, "duplicate": True}
        parent = db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == payload.parent_qr))
        child = db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == payload.child_qr))
        if parent is None or child is None:
            raise APIError(404, "GENEALOGY_ENTITY_NOT_FOUND", "Родитель или дочерняя сущность не найдены")
        if payload.action in {"ATTACH", "DETACH", "REPLACE"} and (parent.entity_type != "WIP" or child.entity_type != "COMPONENT"):
            raise APIError(409, "GENEALOGY_TYPES_INVALID", "ATTACH/DETACH/REPLACE связывает компонент с WIP")
        if child.status == "SCRAPPED":
            raise APIError(409, "SCRAPPED_ENTITY_IMMUTABLE", "Списанную сущность нельзя повторно привязать")
        now = utcnow()
        active = db.scalar(select(GenealogyLink).where(GenealogyLink.child_entity_id == child.id, GenealogyLink.active.is_(True)))
        if payload.action == "ATTACH":
            if active:
                raise APIError(409, "CHILD_ALREADY_BOUND", "Деталь уже активно привязана к изделию")
            link = GenealogyLink(request_id=payload.request_id, action="ATTACH", parent_entity_id=parent.id, child_entity_id=child.id, active=True, reason=payload.reason, created_by_id=context.user.id)
        elif payload.action == "DETACH":
            if active is None or active.parent_entity_id != parent.id:
                raise APIError(409, "ACTIVE_LINK_NOT_FOUND", "Активная привязка не найдена")
            active.active = False
            active.ended_at = now
            active.reason = payload.reason or active.reason
            link = GenealogyLink(request_id=payload.request_id, action="DETACH", parent_entity_id=parent.id, child_entity_id=child.id, active=False, reason=payload.reason, created_by_id=context.user.id, ended_at=now)
        elif payload.action == "REPLACE":
            if active is None or active.parent_entity_id != parent.id or not payload.replacement_qr:
                raise APIError(409, "REPLACEMENT_CONTEXT_INVALID", "Для замены нужна активная старая деталь и новый QR")
            replacement = db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == payload.replacement_qr))
            if replacement is None:
                raise APIError(404, "REPLACEMENT_NOT_FOUND", "Новая деталь не найдена")
            if replacement.entity_type != "COMPONENT" or replacement.status == "SCRAPPED":
                raise APIError(409, "REPLACEMENT_TYPE_INVALID", "Новая сущность должна быть активным компонентом")
            if db.scalar(select(GenealogyLink).where(GenealogyLink.child_entity_id == replacement.id, GenealogyLink.active.is_(True))):
                raise APIError(409, "REPLACEMENT_ALREADY_BOUND", "Новая деталь уже привязана")
            active.active = False
            active.ended_at = now
            link = GenealogyLink(request_id=payload.request_id, action="REPLACE", parent_entity_id=parent.id, child_entity_id=replacement.id, active=True, reason=payload.reason, created_by_id=context.user.id)
        elif payload.action == "FINALIZE":
            if parent.entity_type != "FINAL" or child.entity_type != "WIP":
                raise APIError(409, "FINALIZE_TYPES_INVALID", "FINALIZE связывает final serial с WIP")
            if active:
                raise APIError(409, "WIP_ALREADY_FINALIZED", "WIP уже связан с final serial")
            latest_quality = _latest_effective_quality_decision(db, child.id)
            open_rework = db.scalar(select(ReworkOrder).where(ReworkOrder.entity_id == child.id, ReworkOrder.status.in_(["OPEN", "READY_FOR_QC"])))
            if latest_quality is None or latest_quality.decision != "ACCEPT" or open_rework is not None:
                raise APIError(409, "FINAL_QUALITY_GATE_FAILED", "Final serial разрешён только после положительного ОТК без открытого rework")
            child.status = "FINISHED"
            parent.status = "FINISHED"
            link = GenealogyLink(request_id=payload.request_id, action="FINALIZE", parent_entity_id=parent.id, child_entity_id=child.id, active=True, reason=payload.reason, created_by_id=context.user.id)
        else:  # SCRAP
            child.status = "SCRAPPED"
            if active:
                active.active = False
                active.ended_at = now
            link = GenealogyLink(request_id=payload.request_id, action="SCRAP", parent_entity_id=parent.id, child_entity_id=child.id, active=False, reason=payload.reason, created_by_id=context.user.id, ended_at=now)
        db.add(link)
        db.flush()
        record_audit(db, actor_user_id=context.user.id, action=f"GENEALOGY_{payload.action}", object_type="genealogy_link", object_id=link.id, trace_id=_trace_id(request), after={"parent": parent.qr_code, "child": child.qr_code, "active": link.active}, reason=payload.reason)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise APIError(409, "CONCURRENT_GENEALOGY_CONFLICT", "Деталь была привязана параллельным запросом")
        return {"id": link.id, "action": link.action, "parent_entity_id": link.parent_entity_id, "child_entity_id": link.child_entity_id, "active": link.active, "duplicate": False}

    @app.get(f"{API}/assignments")
    def assignments(shift_id: str | None = None, context: AuthContext = Depends(require_capability("manage_assignments")), db: Session = Depends(get_session)) -> dict:
        query = select(ShiftAssignment).order_by(ShiftAssignment.created_at)
        if shift_id:
            query = query.where(ShiftAssignment.shift_id == shift_id)
        rows = list(db.scalars(query))
        return _page([{"id": x.id, "shift_id": x.shift_id, "employee_id": x.employee_id, "row_id": x.row_id, "workstation_id": x.workstation_id, "route_step_id": x.route_step_id, "status": x.status, "starts_at": x.starts_at.isoformat(), "ends_at": x.ends_at.isoformat()} for x in rows], len(rows), len(rows) or 1, 0)

    @app.post(f"{API}/shifts/{{shift_id}}/assignments", status_code=201)
    def create_assignment(shift_id: str, payload: AssignmentRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("manage_assignments")), db: Session = Depends(get_session)) -> dict:
        if any(db.get(cls, value) is None for cls, value in [(Shift, shift_id), (Employee, payload.employee_id), (ProductionRow, payload.row_id), (Workstation, payload.workstation_id), (RouteStep, payload.route_step_id)]):
            raise APIError(404, "ASSIGNMENT_REFERENCE_NOT_FOUND", "Одна из ссылок назначения не найдена")
        row = db.get(ProductionRow, payload.row_id)
        step = db.get(RouteStep, payload.route_step_id)
        if not (step.row_id == row.id or (step.row_id is None and row.category == "ASSEMBLY")):
            raise APIError(409, "ROW_OPERATION_SCOPE_MISMATCH", "Операция не разрешена на выбранном ряду")
        if payload.ends_at <= payload.starts_at:
            raise APIError(422, "ASSIGNMENT_INTERVAL_INVALID", "Конец назначения должен быть позже начала")
        overlapping = list(db.scalars(select(ShiftAssignment).where(
            ShiftAssignment.shift_id == shift_id,
            ShiftAssignment.employee_id == payload.employee_id,
            ShiftAssignment.status == "ACTIVE",
            ShiftAssignment.starts_at < payload.ends_at,
            ShiftAssignment.ends_at > payload.starts_at,
        )))
        transferred = None
        if payload.transfer_from_assignment_id:
            transferred = db.get(ShiftAssignment, payload.transfer_from_assignment_id)
            if transferred is None or transferred not in overlapping or transferred.shift_id != shift_id or transferred.employee_id != payload.employee_id:
                raise APIError(409, "TRANSFER_SOURCE_INVALID", "Исходное назначение не совпадает с сотрудником, сменой или интервалом")
            if len(overlapping) != 1 or _aware(payload.starts_at) <= _aware(transferred.starts_at):
                raise APIError(409, "TRANSFER_OVERLAP_CONFLICT", "Перевод не должен пересекать другие назначения")
            transferred.ends_at = payload.starts_at
            transferred.status = "ENDED"
        elif overlapping:
            raise APIError(409, "ASSIGNMENT_OVERLAP", "Интервал пересекается с действующим назначением; используйте transfer_from_assignment_id")
        item = ShiftAssignment(shift_id=shift_id, employee_id=payload.employee_id, row_id=payload.row_id, workstation_id=payload.workstation_id, route_step_id=payload.route_step_id, starts_at=payload.starts_at, ends_at=payload.ends_at, status="ACTIVE")
        db.add(item)
        db.flush()
        record_audit(db, actor_user_id=context.user.id, action="ASSIGNMENT_TRANSFERRED" if transferred else "ASSIGNMENT_CREATED", object_type="shift_assignment", object_id=item.id, trace_id=_trace_id(request), before={"ended_assignment_id": transferred.id} if transferred else None, after=payload.model_dump(mode="json"))
        db.commit()
        return {"id": item.id, "status": item.status}

    @app.get(f"{API}/time-entries")
    def time_entries(shift_id: str | None = None, context: AuthContext = Depends(require_capability("manage_time_entries")), db: Session = Depends(get_session)) -> dict:
        query = select(TimeEntry).join(ShiftAssignment, ShiftAssignment.id == TimeEntry.assignment_id).order_by(TimeEntry.created_at)
        if shift_id:
            query = query.where(ShiftAssignment.shift_id == shift_id)
        rows = list(db.scalars(query))
        return _page([{"id": x.id, "assignment_id": x.assignment_id, "category": x.category, "hours": decimal_string(x.hours), "source": x.source, "approval_status": x.approval_status, "version": x.version} for x in rows], len(rows), len(rows) or 1, 0)

    @app.post(f"{API}/time-entries", status_code=201)
    def create_time_entry(payload: TimeEntryRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("manage_time_entries")), db: Session = Depends(get_session)) -> dict:
        if db.get(ShiftAssignment, payload.assignment_id) is None:
            raise APIError(404, "ASSIGNMENT_NOT_FOUND", "Назначение не найдено")
        item = TimeEntry(assignment_id=payload.assignment_id, category=payload.category, hours=payload.hours, source=payload.source, approval_status="APPROVED", version=1, reason=payload.reason)
        db.add(item)
        db.flush()
        record_audit(db, actor_user_id=context.user.id, action="TIME_ENTRY_CREATED", object_type="time_entry", object_id=item.id, trace_id=_trace_id(request), after=payload.model_dump(mode="json"), reason=payload.reason)
        db.commit()
        return {"id": item.id, "hours": decimal_string(item.hours), "approval_status": item.approval_status}

    @app.get(f"{API}/qc-defect-reasons")
    def qc_defect_reasons(
        _context: AuthContext = Depends(require_capability("quality_decide")),
    ) -> dict:
        return {
            "items": [{"code": code, "label": label} for code, label in QC_DEFECT_REASONS.items()],
            "synthetic": True,
        }

    @app.post(f"{API}/qc-inspections")
    def create_qc_inspection(
        payload: QCInspectionRequest,
        request: Request,
        context: AuthContext = Depends(require_csrf_capability("quality_decide")),
        db: Session = Depends(get_session),
    ) -> dict:
        request.state.qc_inspection_id = payload.inspection_id
        body_hash = canonical_payload_hash(payload.model_dump(mode="json"))
        existing_decision = db.scalar(select(QualityDecision).where(QualityDecision.request_id == payload.inspection_id))
        if existing_decision is not None:
            replay = _qc_replay_after_conflict(db, payload.inspection_id, context.user.id, body_hash)
            assert replay is not None
            return replay

        colliding_event = db.get(OperationEvent, payload.inspection_id)
        if colliding_event is not None:
            if colliding_event.user_id != context.user.id:
                raise APIError(403, "QC_INSPECTION_OWNER_MISMATCH", "Идентификатор проверки принадлежит другому оператору")
            raise APIError(409, "QC_INSPECTION_ID_CONFLICT", "UUID уже используется другим событием")
        if payload.decision == "REJECT":
            if payload.defect_code not in QC_DEFECT_REASONS:
                raise APIError(422, "QC_DEFECT_REASON_REQUIRED", "Для брака выберите причину из демонстрационного справочника")
        elif payload.defect_code is not None:
            raise APIError(422, "QC_DEFECT_REASON_NOT_ALLOWED", "Для решения «Годен» причина брака должна быть пустой")

        work_session = db.get(WorkSession, payload.work_session_id)
        if work_session is None:
            raise APIError(404, "WORK_SESSION_NOT_FOUND", "Рабочая сессия не найдена")
        if work_session.user_id != context.user.id:
            raise APIError(403, "WORK_SESSION_OWNER_MISMATCH", "Рабочая сессия принадлежит другому оператору")
        if work_session.ended_at is not None:
            raise APIError(409, "WORK_SESSION_ENDED", "Рабочая сессия уже завершена")
        shift = db.get(Shift, work_session.shift_id)
        if shift is None or shift.status != "RUNNING" or shift.approval_status == "APPROVED":
            raise APIError(409, "SHIFT_NOT_MUTABLE", "Смена закрыта или уже утверждена; новые проверки запрещены")
        assignment = db.get(ShiftAssignment, work_session.assignment_id)
        if (
            assignment is None
            or assignment.status != "ACTIVE"
            or assignment.employee_id != context.user.employee_id
            or assignment.shift_id != work_session.shift_id
            or assignment.row_id != work_session.row_id
            or assignment.workstation_id != work_session.workstation_id
            or assignment.route_step_id != work_session.route_step_id
        ):
            raise APIError(409, "WORK_ASSIGNMENT_INACTIVE", "Назначение изменено или завершено; откройте новую рабочую сессию")
        entity = db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == payload.subject_qr))
        if entity is None:
            raise APIError(404, "ENTITY_NOT_FOUND", "QR не зарегистрирован")
        if entity.status in {"SCRAPPED", "RETIRED", "FINISHED"}:
            raise APIError(409, "ENTITY_NOT_SCANNABLE", "Списанная, архивная или завершённая сущность не принимает контроль")
        step = db.get(RouteStep, work_session.route_step_id)
        row = db.get(ProductionRow, work_session.row_id)
        if step is None or row is None:
            raise APIError(409, "WORK_CONTEXT_INVALID", "Контекст рабочей сессии повреждён")
        if row.category != "QC" or step.row_id != row.id:
            raise APIError(409, "QC_WORK_CONTEXT_REQUIRED", "Проверка доступна только на назначенной операции ряда ОТК")
        if entity.route_version_id != step.route_version_id:
            raise APIError(409, "ROUTE_VERSION_MISMATCH", "Операция ОТК относится к другой версии маршрута изделия")
        if entity.entity_type != step.entity_type:
            raise APIError(409, "ENTITY_TYPE_MISMATCH", "Тип QR не соответствует контрольной операции")

        correction = aliased(OperationEvent)
        event = db.scalar(
            select(OperationEvent)
            .outerjoin(QualityDecision, QualityDecision.operation_event_id == OperationEvent.id)
            .where(
                OperationEvent.shift_id == shift.id,
                OperationEvent.user_id == context.user.id,
                OperationEvent.work_session_id == work_session.id,
                OperationEvent.entity_id == entity.id,
                OperationEvent.route_step_id == step.id,
                OperationEvent.status == "ACCEPTED",
                OperationEvent.event_type == "COMPLETE",
                OperationEvent.correction_of_id.is_(None),
                QualityDecision.id.is_(None),
                ~select(correction.id).where(
                    correction.correction_of_id == OperationEvent.id,
                    correction.status == "ACCEPTED",
                ).exists(),
            )
            .order_by(OperationEvent.server_received_at.desc(), OperationEvent.id.desc())
        )
        rework_order = None
        if event is not None and event.attempt_type == "REWORK":
            if not step.allows_rework:
                raise APIError(409, "REWORK_NOT_AUTHORIZED", "Контрольная операция не разрешает повторную проверку")
            rework_order = db.scalar(
                select(ReworkOrder).where(
                    ReworkOrder.entity_id == entity.id,
                    ReworkOrder.status.in_(["READY_FOR_QC", "REINSPECTED"]),
                ).order_by(ReworkOrder.created_at.desc())
            )
            if rework_order is None:
                raise APIError(409, "REWORK_NOT_AUTHORIZED", "Повторный контроль не связан с разрешённой переделкой")

        if event is None:
            rework_order = db.scalar(
                select(ReworkOrder).where(
                    ReworkOrder.entity_id == entity.id,
                    ReworkOrder.status == "READY_FOR_QC",
                ).order_by(ReworkOrder.created_at.desc())
            )
            projection = db.scalar(select(OperationProjection).where(OperationProjection.entity_id == entity.id))
            if rework_order is None:
                expected = 1 if projection is None else projection.route_position + 1
                if step.sequence != expected:
                    raise APIError(409, "ROUTE_VIOLATION", f"Ожидалась позиция маршрута {expected}, получена {step.sequence}")
                attempt_type = "PRIMARY"
                attempt_no = 1
            else:
                if not step.allows_rework:
                    raise APIError(409, "REWORK_NOT_AUTHORIZED", "Контрольная операция не разрешает повторную проверку")
                attempt_type = "REWORK"
                prior_attempt = db.scalar(
                    select(func.max(OperationEvent.attempt_no)).where(
                        OperationEvent.entity_id == entity.id,
                        OperationEvent.route_step_id == step.id,
                        OperationEvent.event_type == "COMPLETE",
                    )
                ) or 0
                attempt_no = prior_attempt + 1
            plan = latest_approved_plan(db, shift.id)
            plan_line = db.scalar(select(PlanLine).where(
                PlanLine.plan_version_id == plan.id,
                PlanLine.route_step_id == step.id,
                or_(PlanLine.row_id == work_session.row_id, PlanLine.row_id.is_(None)),
            ).order_by(PlanLine.row_id.desc()))
            event = OperationEvent(
                id=payload.inspection_id, payload_hash=body_hash, shift_id=shift.id,
                work_session_id=work_session.id, entity_id=entity.id, route_step_id=step.id,
                plan_line_id=plan_line.id if plan_line else None, user_id=context.user.id,
                attempt_no=attempt_no, attempt_type=attempt_type, event_type="COMPLETE",
                outcome="COMPLETED", status="ACCEPTED", code="QC_INSPECTION_ACCEPTED",
                occurred_at_device=payload.occurred_at_device,
            )
            db.add(event)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                replay = _qc_replay_after_conflict(db, payload.inspection_id, context.user.id, body_hash)
                if replay is not None:
                    return replay
                semantic = db.scalar(select(OperationEvent).where(
                    OperationEvent.entity_id == entity.id,
                    OperationEvent.route_step_id == step.id,
                    OperationEvent.attempt_no == attempt_no,
                    OperationEvent.attempt_type == attempt_type,
                    OperationEvent.event_type == "COMPLETE",
                ))
                if semantic is not None:
                    raise APIError(409, "QC_SEMANTIC_DUPLICATE", "Эта контрольная попытка уже сохранена другим UUID")
                raise APIError(409, "QC_INSPECTION_IN_PROGRESS", "Результат конкурентной проверки пока не определён; повторите тот же UUID")
            if projection is None:
                db.add(OperationProjection(
                    entity_id=entity.id, last_event_id=event.id, last_route_step_id=step.id,
                    route_position=step.sequence, status="IN_PROGRESS", version=1,
                ))
            elif attempt_type == "PRIMARY":
                projection.last_event_id = event.id
                projection.last_route_step_id = step.id
                projection.route_position = step.sequence
                projection.version += 1

        decision = QualityDecision(
            request_id=payload.inspection_id, entity_id=entity.id, shift_id=shift.id,
            operation_event_id=event.id, inspector_user_id=context.user.id,
            decision=payload.decision, defect_code=payload.defect_code,
        )
        db.add(decision)
        try:
            db.flush()
            if event.attempt_type == "REWORK" and rework_order is not None:
                rework_order.status = "REINSPECTED"
            record_audit(
                db,
                actor_user_id=context.user.id,
                action="QC_INSPECTION_RECORDED",
                object_type="quality_decision",
                object_id=decision.id,
                trace_id=_trace_id(request),
                after={
                    "inspection_id": payload.inspection_id,
                    "payload_hash": body_hash,
                    "operation_event_id": event.id,
                    "decision": payload.decision,
                    "defect_code": payload.defect_code,
                },
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            replay = _qc_replay_after_conflict(db, payload.inspection_id, context.user.id, body_hash)
            if replay is not None:
                return replay
            linked = db.scalar(select(QualityDecision).where(QualityDecision.operation_event_id == event.id))
            if linked is not None:
                raise APIError(409, "QC_SEMANTIC_DUPLICATE", "Для контрольного события уже сохранено решение другим UUID")
            raise APIError(409, "QC_INSPECTION_IN_PROGRESS", "Результат конкурентной проверки пока не определён; повторите тот же UUID")
        return _qc_inspection_response(db, decision, duplicate=False)

    @app.get(f"{API}/qc-inspections/{{inspection_id}}/status")
    def qc_inspection_status(
        inspection_id: str,
        context: AuthContext = Depends(require_capability("quality_decide")),
        db: Session = Depends(get_session),
    ) -> dict:
        decision = db.scalar(select(QualityDecision).where(QualityDecision.request_id == inspection_id))
        if decision is None:
            event = db.get(OperationEvent, inspection_id)
            if event is not None and event.user_id != context.user.id:
                raise APIError(403, "QC_INSPECTION_OWNER_MISMATCH", "Статус чужой проверки недоступен")
            return {
                "inspection_id": inspection_id,
                "status": "NOT_FOUND",
                "accepted": False,
                "terminal": False,
                "retryable": True,
                "duplicate": False,
                "next_steps": ["RETRY_SAME_UUID"],
                "inspection": None,
            }
        if decision.inspector_user_id != context.user.id:
            raise APIError(403, "QC_INSPECTION_OWNER_MISMATCH", "Статус чужой проверки недоступен")
        return _qc_inspection_response(db, decision, duplicate=False)

    @app.get(f"{API}/me/qc-shift-activity")
    def my_qc_shift_activity(
        limit: int = Query(default=10, ge=1, le=10),
        context: AuthContext = Depends(require_capability("quality_decide")),
        db: Session = Depends(get_session),
    ) -> dict:
        shift = db.scalar(select(Shift).where(Shift.status == "RUNNING").order_by(Shift.starts_at.desc()))
        if shift is None:
            raise APIError(404, "ACTIVE_SHIFT_NOT_FOUND", "Активная смена не найдена")
        correction = aliased(OperationEvent)
        decisions = list(db.scalars(
            select(QualityDecision)
            .join(OperationEvent, OperationEvent.id == QualityDecision.operation_event_id)
            .where(
                QualityDecision.inspector_user_id == context.user.id,
                QualityDecision.shift_id == shift.id,
                OperationEvent.status == "ACCEPTED",
                OperationEvent.event_type == "COMPLETE",
                OperationEvent.correction_of_id.is_(None),
                ~select(correction.id).where(
                    correction.correction_of_id == OperationEvent.id,
                    correction.status == "ACCEPTED",
                ).exists(),
            )
            .order_by(QualityDecision.created_at.desc(), QualityDecision.id.desc())
        ))
        history_decisions = list(db.scalars(
            select(QualityDecision)
            .join(OperationEvent, OperationEvent.id == QualityDecision.operation_event_id)
            .where(
                QualityDecision.inspector_user_id == context.user.id,
                QualityDecision.shift_id == shift.id,
                OperationEvent.event_type == "COMPLETE",
            )
            .order_by(QualityDecision.created_at.desc(), QualityDecision.id.desc())
            .limit(limit)
        ))
        active_session = db.scalar(
            select(WorkSession)
            .join(ShiftAssignment, ShiftAssignment.id == WorkSession.assignment_id)
            .join(ProductionRow, ProductionRow.id == WorkSession.row_id)
            .where(
                WorkSession.user_id == context.user.id,
                WorkSession.shift_id == shift.id,
                WorkSession.ended_at.is_(None),
                ShiftAssignment.status == "ACTIVE",
                ProductionRow.category == "QC",
            )
            .order_by(WorkSession.started_at.desc(), WorkSession.id.desc())
        )
        session_context = None
        if active_session is not None:
            row = db.get(ProductionRow, active_session.row_id)
            step = db.get(RouteStep, active_session.route_step_id)
            if row is not None and step is not None:
                session_context = {
                    "work_session_id": active_session.id,
                    "row": {"id": row.id, "code": row.code, "name": row.name},
                    "route_step": {"id": step.id, "code": step.code, "name": step.name},
                }
        recent_inspections = [
            {"inspection_id": decision.request_id, **_qc_inspection_payload(db, decision)}
            for decision in history_decisions
        ]
        accepted_count = sum(decision.decision == "ACCEPT" for decision in decisions)
        rejected_count = sum(decision.decision == "REJECT" for decision in decisions)
        reinspection_count = sum(
            db.get(OperationEvent, decision.operation_event_id).attempt_type == "REWORK"
            for decision in decisions
        )
        return {
            "shift": {"id": shift.id, "code": shift.code, "production_date": shift.production_date},
            "context": session_context,
            "checked_count": len(decisions),
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "first_pass_count": len(decisions) - reinspection_count,
            "reinspection_count": reinspection_count,
            "recent_inspections": recent_inspections,
            "note": "Найденный брак считается выполненной проверкой ОТК; это не персональный KPI контролёра.",
        }

    @app.post(f"{API}/quality/decisions", status_code=201)
    def quality_decision(payload: QualityDecisionRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("quality_decide")), db: Session = Depends(get_session)) -> dict:
        existing = db.scalar(select(QualityDecision).where(QualityDecision.request_id == payload.request_id))
        if existing:
            return {"id": existing.id, "decision": existing.decision, "duplicate": True}
        entity = db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == payload.entity_qr))
        if entity is None:
            raise APIError(404, "ENTITY_NOT_FOUND", "Изделие не найдено")
        qc_event = db.scalar(
            select(OperationEvent).join(RouteStep, RouteStep.id == OperationEvent.route_step_id)
            .outerjoin(QualityDecision, QualityDecision.operation_event_id == OperationEvent.id)
            .where(OperationEvent.entity_id == entity.id, OperationEvent.status == "ACCEPTED", RouteStep.code.like("%QC%"), QualityDecision.id.is_(None))
            .order_by(OperationEvent.server_received_at.desc())
        )
        if qc_event is None:
            raise APIError(409, "QC_EVENT_REQUIRED", "Нет непроверенного события ОТК")
        if payload.decision == "REJECT" and not payload.defect_code:
            raise APIError(422, "DEFECT_CODE_REQUIRED", "Для отклонения нужен код дефекта")
        item = QualityDecision(request_id=payload.request_id, entity_id=entity.id, shift_id=qc_event.shift_id, operation_event_id=qc_event.id, inspector_user_id=context.user.id, decision=payload.decision, defect_code=payload.defect_code, note=payload.note)
        db.add(item)
        db.flush()
        record_audit(db, actor_user_id=context.user.id, action="QUALITY_DECISION", object_type="quality_decision", object_id=item.id, trace_id=_trace_id(request), after=payload.model_dump(mode="json"))
        db.commit()
        return {"id": item.id, "decision": item.decision, "entity_id": item.entity_id, "duplicate": False}

    @app.get(f"{API}/quality/decisions")
    def quality_decisions(context: AuthContext = Depends(require_capability("read_entities")), db: Session = Depends(get_session)) -> dict:
        rows = list(db.scalars(select(QualityDecision).order_by(QualityDecision.created_at.desc())))
        return _page([{
            "id": item.id, "request_id": item.request_id, "entity_id": item.entity_id,
            "shift_id": item.shift_id, "operation_event_id": item.operation_event_id,
            "inspector_user_id": item.inspector_user_id, "decision": item.decision,
            "defect_code": item.defect_code, "note": item.note, "created_at": item.created_at.isoformat(),
        } for item in rows], len(rows), len(rows) or 1, 0)

    @app.post(f"{API}/quality/audits", status_code=201)
    def quality_audit(payload: QualityAuditRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("quality_audit")), db: Session = Depends(get_session)) -> dict:
        existing = db.scalar(select(QualityAudit).where(QualityAudit.request_id == payload.request_id))
        if existing:
            return {"id": existing.id, "result": existing.result, "duplicate": True}
        decision = db.get(QualityDecision, payload.decision_id)
        if decision is None:
            raise APIError(404, "QUALITY_DECISION_NOT_FOUND", "Решение ОТК не найдено")
        if decision.inspector_user_id == context.user.id:
            raise APIError(409, "AUDIT_NOT_INDEPENDENT", "Контролёр не может аудировать собственное решение")
        if db.scalar(select(QualityAudit).where(QualityAudit.decision_id == decision.id)):
            raise APIError(409, "AUDIT_ALREADY_EXISTS", "Решение уже имеет независимый аудит")
        item = QualityAudit(request_id=payload.request_id, decision_id=decision.id, auditor_user_id=context.user.id, result=payload.result, note=payload.note)
        db.add(item)
        db.flush()
        record_audit(db, actor_user_id=context.user.id, action="QUALITY_AUDITED", object_type="quality_audit", object_id=item.id, trace_id=_trace_id(request), after=payload.model_dump(mode="json"))
        db.commit()
        return {"id": item.id, "result": item.result, "duplicate": False}

    @app.get(f"{API}/quality/audits")
    def quality_audits(context: AuthContext = Depends(require_capability("read_entities")), db: Session = Depends(get_session)) -> dict:
        rows = list(db.scalars(select(QualityAudit).order_by(QualityAudit.created_at.desc())))
        return _page([{
            "id": item.id, "request_id": item.request_id, "decision_id": item.decision_id,
            "auditor_user_id": item.auditor_user_id, "result": item.result,
            "note": item.note, "created_at": item.created_at.isoformat(),
        } for item in rows], len(rows), len(rows) or 1, 0)

    @app.post(f"{API}/rework-orders", status_code=201)
    def create_rework(payload: ReworkOrderRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("manage_rework")), db: Session = Depends(get_session)) -> dict:
        existing = db.scalar(select(ReworkOrder).where(ReworkOrder.request_id == payload.request_id))
        if existing:
            return {"id": existing.id, "status": existing.status, "duplicate": True}
        entity = db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == payload.entity_qr))
        decision = db.get(QualityDecision, payload.quality_decision_id)
        step = db.get(RouteStep, payload.requested_route_step_id)
        if entity is None or decision is None or step is None:
            raise APIError(404, "REWORK_REFERENCE_NOT_FOUND", "Ссылка rework не найдена")
        latest_decision = _latest_effective_quality_decision(db, entity.id)
        active_rework = db.scalar(select(ReworkOrder).where(
            ReworkOrder.entity_id == entity.id,
            ReworkOrder.status.in_(["OPEN", "READY_FOR_QC"]),
        ))
        if (
            decision.entity_id != entity.id
            or latest_decision is None
            or latest_decision.id != decision.id
            or decision.decision != "REJECT"
            or not step.allows_rework
            or step.route_version_id != entity.route_version_id
        ):
            raise APIError(409, "REWORK_CONTEXT_INVALID", "Rework разрешён только после отказа ОТК на допустимой операции")
        if active_rework is not None:
            raise APIError(409, "REWORK_ALREADY_OPEN", "Для изделия уже открыт цикл переделки")
        item = ReworkOrder(request_id=payload.request_id, entity_id=entity.id, quality_decision_id=decision.id, requested_route_step_id=step.id, status="OPEN", created_by_id=context.user.id, reason=payload.reason)
        db.add(item)
        db.flush()
        record_audit(db, actor_user_id=context.user.id, action="REWORK_OPENED", object_type="rework_order", object_id=item.id, trace_id=_trace_id(request), after=payload.model_dump(mode="json"), reason=payload.reason)
        db.commit()
        return {"id": item.id, "status": item.status, "duplicate": False}

    @app.get(f"{API}/rework-orders")
    def rework_orders(context: AuthContext = Depends(require_capability("read_entities")), db: Session = Depends(get_session)) -> dict:
        rows = list(db.scalars(select(ReworkOrder).order_by(ReworkOrder.created_at.desc())))
        return _page([{
            "id": item.id, "request_id": item.request_id, "entity_id": item.entity_id,
            "quality_decision_id": item.quality_decision_id, "requested_route_step_id": item.requested_route_step_id,
            "status": item.status, "created_by_id": item.created_by_id, "reason": item.reason,
            "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat(),
        } for item in rows], len(rows), len(rows) or 1, 0)

    @app.get(f"{API}/plans")
    def plans(shift_id: str | None = None, context: AuthContext = Depends(require_capability("view_reports")), db: Session = Depends(get_session)) -> dict:
        query = select(ProductionPlanVersion).order_by(ProductionPlanVersion.version.desc())
        if shift_id:
            query = query.where(ProductionPlanVersion.shift_id == shift_id)
        items = list(db.scalars(query))
        result = []
        for plan in items:
            lines = list(db.scalars(select(PlanLine).where(PlanLine.plan_version_id == plan.id).order_by(PlanLine.key)))
            result.append({"id": plan.id, "shift_id": plan.shift_id, "version": plan.version, "status": plan.status, "approved_at": plan.approved_at.isoformat() if plan.approved_at else None, "lines": [{"id": line.id, "key": line.key, "model_id": line.model_id, "route_step_id": line.route_step_id, "row_id": line.row_id, "planned_qty": line.planned_qty, "norm_minutes": decimal_string(line.norm_minutes) if line.norm_minutes is not None else None} for line in lines]})
        return _page(result, len(result), len(result) or 1, 0)

    @app.post(f"{API}/plans", status_code=201)
    def create_plan(payload: PlanCreateRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("manage_plans")), db: Session = Depends(get_session)) -> dict:
        if len({line.key for line in payload.lines}) != len(payload.lines):
            raise APIError(422, "DUPLICATE_PLAN_KEY", "Ключи строк плана должны быть уникальны")
        latest = db.scalar(select(ProductionPlanVersion).where(ProductionPlanVersion.shift_id == payload.shift_id).order_by(ProductionPlanVersion.version.desc()))
        version = (latest.version + 1) if latest else 1
        if payload.mode == "FULL" and not payload.confirm_full_replacement:
            raise APIError(409, "FULL_REPLACEMENT_CONFIRMATION_REQUIRED", "Полная замена требует явного подтверждения")
        effective_lines: dict[str, dict] = {}
        if latest is not None and payload.mode == "PATCH":
            for previous in db.scalars(select(PlanLine).where(PlanLine.plan_version_id == latest.id)):
                effective_lines[previous.key] = {
                    "key": previous.key, "model_id": previous.model_id,
                    "route_step_id": previous.route_step_id, "row_id": previous.row_id,
                    "planned_qty": previous.planned_qty, "norm_minutes": previous.norm_minutes,
                }
        for line in payload.lines:
            effective_lines[line.key] = line.model_dump()
        if payload.mode == "FULL":
            effective_lines = {line.key: line.model_dump() for line in payload.lines}
        if not effective_lines:
            raise APIError(422, "PLAN_LINES_REQUIRED", "План должен содержать хотя бы одну строку")
        first_line = next(iter(effective_lines.values()))
        standard = db.scalar(select(StandardSetVersion).where(StandardSetVersion.model_id == first_line["model_id"], StandardSetVersion.status == "APPROVED").order_by(StandardSetVersion.version.desc()))
        if standard is None:
            raise APIError(409, "APPROVED_STANDARD_MISSING", "Перед планом утвердите версию норм")
        norm_by_step = {
            value.route_step_id: value.norm_minutes
            for value in db.scalars(select(StandardValue).where(StandardValue.standard_set_id == standard.id))
        }
        for line in effective_lines.values():
            line["norm_minutes"] = norm_by_step.get(line["route_step_id"])
        item = ProductionPlanVersion(shift_id=payload.shift_id, standard_version_id=standard.id, version=version, status=payload.status, supersedes_id=latest.id if latest else None, approved_at=utcnow() if payload.status == "APPROVED" else None, approved_by_id=context.user.id if payload.status == "APPROVED" else None, reason=payload.reason)
        db.add(item)
        db.flush()
        seen: set[str] = set()
        for line in effective_lines.values():
            if line["key"] in seen:
                raise APIError(422, "DUPLICATE_PLAN_KEY", "Ключи строк плана должны быть уникальны")
            seen.add(line["key"])
            db.add(PlanLine(plan_version_id=item.id, **line))
        record_audit(db, actor_user_id=context.user.id, action="PLAN_VERSION_CREATED", object_type="production_plan_version", object_id=item.id, trace_id=_trace_id(request), after={"version": version, "status": item.status}, reason=payload.reason)
        db.commit()
        return {"id": item.id, "version": item.version, "status": item.status}

    @app.get(f"{API}/standards")
    def standards(context: AuthContext = Depends(require_capability("view_reports")), db: Session = Depends(get_session)) -> dict:
        items = list(db.scalars(select(StandardSetVersion).order_by(StandardSetVersion.version.desc())))
        result = []
        for item in items:
            values = list(db.scalars(select(StandardValue).where(StandardValue.standard_set_id == item.id)))
            result.append({"id": item.id, "model_id": item.model_id, "version": item.version, "status": item.status, "effective_from": item.effective_from.isoformat(), "effective_to": item.effective_to.isoformat() if item.effective_to else None, "values": [{"route_step_id": value.route_step_id, "norm_minutes": decimal_string(value.norm_minutes)} for value in values]})
        return _page(result, len(result), len(result) or 1, 0)

    @app.post(f"{API}/standards", status_code=201)
    def create_standard(payload: StandardCreateRequest, request: Request, context: AuthContext = Depends(require_csrf_capability("manage_standards")), db: Session = Depends(get_session)) -> dict:
        if len({value.route_step_id for value in payload.values}) != len(payload.values):
            raise APIError(422, "DUPLICATE_STANDARD_STEP", "Операция нормы должна быть уникальна")
        latest = db.scalar(select(StandardSetVersion).where(StandardSetVersion.model_id == payload.model_id).order_by(StandardSetVersion.version.desc()))
        version = (latest.version + 1) if latest else 1
        if payload.mode == "FULL" and not payload.confirm_full_replacement:
            raise APIError(409, "FULL_REPLACEMENT_CONFIRMATION_REQUIRED", "Полная замена требует явного подтверждения")
        effective_values: dict[str, dict] = {}
        if latest is not None and payload.mode == "PATCH":
            for previous in db.scalars(select(StandardValue).where(StandardValue.standard_set_id == latest.id)):
                effective_values[previous.route_step_id] = {"route_step_id": previous.route_step_id, "norm_minutes": previous.norm_minutes}
        for value in payload.values:
            effective_values[value.route_step_id] = value.model_dump()
        if payload.mode == "FULL":
            effective_values = {value.route_step_id: value.model_dump() for value in payload.values}
        if not effective_values:
            raise APIError(422, "STANDARD_VALUES_REQUIRED", "Версия норм должна содержать операции")
        item = StandardSetVersion(model_id=payload.model_id, version=version, status=payload.status, effective_from=payload.effective_from, supersedes_id=latest.id if latest else None, approved_at=utcnow() if payload.status == "APPROVED" else None, approved_by_id=context.user.id if payload.status == "APPROVED" else None)
        db.add(item)
        db.flush()
        seen: set[str] = set()
        for value in effective_values.values():
            if value["route_step_id"] in seen:
                raise APIError(422, "DUPLICATE_STANDARD_STEP", "Операция нормы должна быть уникальна")
            seen.add(value["route_step_id"])
            db.add(StandardValue(standard_set_id=item.id, **value))
        record_audit(db, actor_user_id=context.user.id, action="STANDARD_VERSION_CREATED", object_type="standard_set_version", object_id=item.id, trace_id=_trace_id(request), after={"version": version, "status": item.status}, reason=payload.reason)
        db.commit()
        return {"id": item.id, "version": item.version, "status": item.status}

    @app.get(f"{API}/shifts/{{shift_id}}/calculation")
    def shift_calculation(shift_id: str, context: AuthContext = Depends(require_capability("view_reports")), db: Session = Depends(get_session)) -> dict:
        return calculate_shift(db, shift_id)

    @app.post(f"{API}/shifts/{{shift_id}}/approve")
    def approve_shift(shift_id: str, request: Request, context: AuthContext = Depends(require_csrf_capability("approve_shift")), db: Session = Depends(get_session)) -> dict:
        shift = db.get(Shift, shift_id)
        if shift is None:
            raise APIError(404, "SHIFT_NOT_FOUND", "Смена не найдена")
        existing = db.scalar(select(CalculationSnapshot).where(CalculationSnapshot.shift_id == shift.id, CalculationSnapshot.shift_version == shift.version))
        if existing:
            return {"snapshot_id": existing.id, "approval_status": shift.approval_status, "duplicate": True}
        metrics = calculate_shift(db, shift.id)
        if metrics["kpi_official"] is None:
            raise APIError(409, "OFFICIAL_KPI_UNAVAILABLE", "Нельзя утвердить смену без официального KPI")
        metrics["approval_status"] = "APPROVED"
        snapshot = CalculationSnapshot(
            shift_id=shift.id, plan_version_id=metrics["trace"]["plan_version_id"],
            standard_version_id=metrics["trace"]["standard_version_id"], shift_version=shift.version,
            input_hash=calculation_input_hash(metrics), metrics=metrics,
            trace=metrics["trace"], approved_by_id=context.user.id,
        )
        db.add(snapshot)
        shift.approval_status = "APPROVED"
        db.flush()
        record_audit(db, actor_user_id=context.user.id, action="SHIFT_APPROVED", object_type="calculation_snapshot", object_id=snapshot.id, trace_id=_trace_id(request), after={"input_hash": snapshot.input_hash})
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise APIError(409, "SHIFT_ALREADY_APPROVED", "Эта версия смены уже утверждена")
        return {"snapshot_id": snapshot.id, "approval_status": shift.approval_status, "duplicate": False, "metrics": snapshot.metrics}

    def report_data(db: Session, shift_id: str) -> tuple[dict, str | None]:
        snapshot = db.scalar(select(CalculationSnapshot).where(CalculationSnapshot.shift_id == shift_id).order_by(CalculationSnapshot.approved_at.desc()))
        if snapshot:
            return snapshot.metrics, snapshot.id
        return calculate_shift(db, shift_id), None

    @app.get(f"{API}/reports/{{shift_id}}.csv")
    def report_csv(shift_id: str, context: AuthContext = Depends(require_capability("view_reports")), db: Session = Depends(get_session)) -> StreamingResponse:
        data, snapshot_id = report_data(db, shift_id)
        output = StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["shift_id", "snapshot_id", "metric", "value", "synthetic"])
        for key in ["approval_status", "maturity_state", "a_plan", "a_volume", "p", "q", "kpi_raw", "kpi_official"]:
            writer.writerow([shift_id, snapshot_id or "", key, data.get(key), "true"])
        response = StreamingResponse(iter([output.getvalue().encode("utf-8-sig")]), media_type="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = f'attachment; filename="demo-shift-{shift_id}.csv"'
        return response

    @app.get(f"{API}/reports/{{shift_id}}")
    def report(shift_id: str, context: AuthContext = Depends(require_capability("view_reports")), db: Session = Depends(get_session)) -> dict:
        data, snapshot_id = report_data(db, shift_id)
        return {"shift_id": shift_id, "snapshot_id": snapshot_id, "frozen": snapshot_id is not None, "calculation": data, "synthetic": True}

    @app.get(f"{API}/audit")
    def audit_log(
        limit: int = Query(default=50, ge=1, le=200),
        cursor: int = Query(default=0, ge=0),
        context: AuthContext = Depends(require_capability("view_audit")),
        db: Session = Depends(get_session),
    ) -> dict:
        total = db.scalar(select(func.count()).select_from(AuditEvent)) or 0
        rows = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).offset(cursor).limit(limit)))
        return _page([{"id": x.id, "actor_user_id": x.actor_user_id, "action": x.action, "object_type": x.object_type, "object_id": x.object_id, "before": x.before, "after": x.after, "reason": x.reason, "trace_id": x.trace_id, "created_at": x.created_at.isoformat()} for x in rows], total, limit, cursor)

    return app


app = create_app()

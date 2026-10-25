from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import APIError
from app.models import ProductModel, ProductionRow, RouteStep, RouteVersion, TrackedEntity
from app.security import AuthContext, require_capability, require_csrf_capability
from app.services import record_audit


router = APIRouter(prefix="/api/v1", tags=["configuration"])

ENTITY_TYPES = {"COMPONENT", "WIP", "FINAL"}
ROW_CATEGORIES = {"ASSEMBLY", "SOLDER", "QC"}


class RouteStepCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=140)
    sequence: int = Field(ge=1, le=999)
    entity_type: Literal["COMPONENT", "WIP"]
    allowed_row_ids: list[str] = Field(min_length=1)
    allows_rework: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("allowed_row_ids")
    @classmethod
    def unique_rows(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_row_ids must not contain duplicates")
        return value


class RouteVersionCreate(BaseModel):
    model_id: str
    steps: list[RouteStepCreate] = Field(min_length=1)


class TrackedEntityCreate(BaseModel):
    qr_code: str = Field(min_length=1, max_length=128)
    entity_type: Literal["COMPONENT", "WIP", "FINAL"]
    route_version_id: str
    final_serial: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("qr_code")
    @classmethod
    def normalize_qr(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("qr_code must not be blank")
        return normalized

    @field_validator("final_serial")
    @classmethod
    def normalize_final_serial(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("final_serial must not be blank")
        return normalized


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "configuration-api")


def _row_payload(row: ProductionRow) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "category": row.category,
    }


def _all_assembly_rows(db: Session) -> list[ProductionRow]:
    return list(
        db.scalars(
            select(ProductionRow)
            .where(ProductionRow.category == "ASSEMBLY")
            .order_by(ProductionRow.sort_order, ProductionRow.code)
        )
    )


def _allowed_rows(db: Session, step: RouteStep) -> tuple[list[ProductionRow], str]:
    if step.row_id is not None:
        row = db.get(ProductionRow, step.row_id)
        return ([row] if row is not None else []), "EXACT_ROW"
    if step.row_id is None:
        return _all_assembly_rows(db), "ASSEMBLY_CATEGORY"
    return [], "UNSCOPED"


def _step_payload(db: Session, step: RouteStep) -> dict:
    rows, row_scope = _allowed_rows(db, step)
    return {
        "id": step.id,
        "code": step.code,
        "name": step.name,
        "sequence": step.sequence,
        "entity_type": step.entity_type,
        "allowed_rows": [_row_payload(row) for row in rows],
        "row_scope": row_scope,
        "allows_rework": step.allows_rework,
    }


def _route_payload(db: Session, route: RouteVersion) -> dict:
    model = db.get(ProductModel, route.model_id)
    steps = list(
        db.scalars(
            select(RouteStep)
            .where(RouteStep.route_version_id == route.id)
            .order_by(RouteStep.sequence)
        )
    )
    return {
        "id": route.id,
        "model": {
            "id": model.id,
            "code": model.code,
            "name": model.name,
        } if model is not None else None,
        "version": route.version,
        "status": route.status,
        "immutable": route.status == "APPROVED",
        "steps": [_step_payload(db, step) for step in steps],
    }


def _entity_payload(entity: TrackedEntity) -> dict:
    return {
        "id": entity.id,
        "qr_code": entity.qr_code,
        "entity_type": entity.entity_type,
        "model_id": entity.model_id,
        "route_version_id": entity.route_version_id,
        "status": entity.status,
        "final_serial": entity.final_serial,
    }


def _domain_error(code: str, message: str, field: str) -> APIError:
    return APIError(422, code, message, [{"field": field, "message": message}])


def _validate_steps(
    db: Session,
    requested: list[RouteStepCreate],
) -> list[tuple[RouteStepCreate, str | None]]:
    sequences = [step.sequence for step in requested]
    if len(sequences) != len(set(sequences)):
        raise _domain_error("ROUTE_SEQUENCE_DUPLICATE", "Порядковые номера операций должны быть уникальны", "steps.sequence")
    if sorted(sequences) != list(range(1, len(requested) + 1)):
        raise _domain_error("ROUTE_SEQUENCE_NOT_CONTIGUOUS", "Последовательность должна начинаться с 1 и не иметь пропусков", "steps.sequence")

    codes = [step.code for step in requested]
    if len(codes) != len(set(codes)):
        raise _domain_error("ROUTE_STEP_CODE_DUPLICATE", "Коды операций внутри версии должны быть уникальны", "steps.code")

    assembly_rows = _all_assembly_rows(db)
    assembly_ids = {row.id for row in assembly_rows}
    if not assembly_rows:
        raise APIError(409, "ASSEMBLY_ROWS_MISSING", "Не настроены сборочные ряды")

    result: list[tuple[RouteStepCreate, str | None]] = []
    for index, step in enumerate(requested):
        rows = list(db.scalars(select(ProductionRow).where(ProductionRow.id.in_(step.allowed_row_ids))))
        if len(rows) != len(step.allowed_row_ids):
            raise _domain_error("ROUTE_ROW_NOT_FOUND", "Один или несколько разрешённых рядов не найдены", f"steps.{index}.allowed_row_ids")
        unknown_categories = sorted({row.category for row in rows} - ROW_CATEGORIES)
        if unknown_categories:
            raise _domain_error("ROUTE_ROW_CATEGORY_INVALID", "Категория ряда не поддерживается в P0", f"steps.{index}.allowed_row_ids")

        if len(rows) == 1:
            result.append((step, rows[0].id))
            continue

        requested_ids = {row.id for row in rows}
        if {row.category for row in rows} != {"ASSEMBLY"}:
            raise _domain_error(
                "ROUTE_ALTERNATIVES_UNSUPPORTED",
                "В P0 несколько альтернативных рядов допустимы только внутри категории ASSEMBLY",
                f"steps.{index}.allowed_row_ids",
            )
        if requested_ids != assembly_ids:
            raise _domain_error(
                "ROUTE_ASSEMBLY_SUBSET_UNSUPPORTED",
                "Текущая модель хранит только полный набор альтернативных сборочных рядов",
                f"steps.{index}.allowed_row_ids",
            )
        result.append((step, None))
    return result


@router.get("/route-versions")
def list_route_versions(
    model_id: str | None = None,
    status: Literal["DRAFT", "APPROVED"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _context: AuthContext = Depends(require_capability("view_reports")),
    db: Session = Depends(get_session),
) -> dict:
    filters = []
    if model_id is not None:
        filters.append(RouteVersion.model_id == model_id)
    if status is not None:
        filters.append(RouteVersion.status == status)
    total = db.scalar(select(func.count()).select_from(RouteVersion).where(*filters)) or 0
    routes = list(
        db.scalars(
            select(RouteVersion)
            .where(*filters)
            .order_by(RouteVersion.model_id, RouteVersion.version.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return {
        "items": [_route_payload(db, route) for route in routes],
        "total": total,
        "next_cursor": str(offset + limit) if offset + limit < total else None,
    }


@router.post("/route-versions", status_code=201)
def create_route_version(
    payload: RouteVersionCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf_capability("manage_standards")),
    db: Session = Depends(get_session),
) -> dict:
    model = db.get(ProductModel, payload.model_id)
    if model is None:
        raise _domain_error("PRODUCT_MODEL_NOT_FOUND", "Модель изделия не найдена", "model_id")
    validated = _validate_steps(db, payload.steps)
    latest = db.scalar(select(func.max(RouteVersion.version)).where(RouteVersion.model_id == model.id)) or 0
    route = RouteVersion(model_id=model.id, version=latest + 1, status="DRAFT")
    db.add(route)
    db.flush()
    for step, row_id in sorted(validated, key=lambda item: item[0].sequence):
        db.add(RouteStep(
            route_version_id=route.id,
            code=step.code,
            name=step.name,
            sequence=step.sequence,
            row_id=row_id,
            entity_type=step.entity_type,
            allows_rework=step.allows_rework,
        ))
    db.flush()
    record_audit(
        db,
        actor_user_id=context.user.id,
        action="ROUTE_VERSION_CREATED",
        object_type="route_version",
        object_id=route.id,
        trace_id=_trace_id(request),
        after={"model_id": route.model_id, "version": route.version, "status": route.status},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise APIError(409, "ROUTE_VERSION_CONFLICT", "Версия маршрута уже создана конкурентным запросом") from exc
    return _route_payload(db, route)


@router.post("/route-versions/{route_version_id}/publish")
def publish_route_version(
    route_version_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf_capability("manage_standards")),
    db: Session = Depends(get_session),
) -> dict:
    route = db.get(RouteVersion, route_version_id)
    if route is None:
        raise APIError(404, "ROUTE_VERSION_NOT_FOUND", "Версия маршрута не найдена")
    if route.status == "APPROVED":
        raise APIError(409, "ROUTE_VERSION_IMMUTABLE", "Опубликованная версия маршрута неизменяема")
    steps = list(db.scalars(select(RouteStep).where(RouteStep.route_version_id == route.id)))
    if not steps:
        raise APIError(409, "ROUTE_VERSION_EMPTY", "Нельзя опубликовать маршрут без операций")
    route.status = "APPROVED"
    record_audit(
        db,
        actor_user_id=context.user.id,
        action="ROUTE_VERSION_PUBLISHED",
        object_type="route_version",
        object_id=route.id,
        trace_id=_trace_id(request),
        before={"status": "DRAFT"},
        after={"status": "APPROVED"},
    )
    db.commit()
    return _route_payload(db, route)


@router.get("/tracked-entities")
def list_tracked_entities(
    entity_type: Literal["COMPONENT", "WIP", "FINAL"] | None = None,
    route_version_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _context: AuthContext = Depends(require_capability("read_entities")),
    db: Session = Depends(get_session),
) -> dict:
    filters = [TrackedEntity.entity_type.in_(ENTITY_TYPES)]
    if entity_type is not None:
        filters.append(TrackedEntity.entity_type == entity_type)
    if route_version_id is not None:
        filters.append(TrackedEntity.route_version_id == route_version_id)
    total = db.scalar(select(func.count()).select_from(TrackedEntity).where(*filters)) or 0
    entities = list(
        db.scalars(
            select(TrackedEntity)
            .where(*filters)
            .order_by(TrackedEntity.created_at, TrackedEntity.qr_code)
            .limit(limit)
            .offset(offset)
        )
    )
    return {
        "items": [_entity_payload(entity) for entity in entities],
        "total": total,
        "next_cursor": str(offset + limit) if offset + limit < total else None,
    }


@router.post("/tracked-entities", status_code=201)
def create_tracked_entity(
    payload: TrackedEntityCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf_capability("manage_genealogy")),
    db: Session = Depends(get_session),
) -> dict:
    route = db.get(RouteVersion, payload.route_version_id)
    if route is None:
        raise _domain_error("ROUTE_VERSION_NOT_FOUND", "Версия маршрута не найдена", "route_version_id")
    if route.status != "APPROVED":
        raise APIError(409, "ROUTE_VERSION_NOT_PUBLISHED", "Объект можно создать только для опубликованного маршрута")
    if payload.entity_type != "FINAL" and payload.final_serial is not None:
        raise _domain_error("FINAL_SERIAL_NOT_ALLOWED", "final_serial допустим только для FINAL", "final_serial")
    existing = db.scalar(select(TrackedEntity).where(TrackedEntity.qr_code == payload.qr_code))
    if existing is not None:
        raise APIError(409, "QR_ALREADY_EXISTS", "QR уже принадлежит другому объекту")
    final_serial = (payload.final_serial or payload.qr_code) if payload.entity_type == "FINAL" else None
    if final_serial is not None and db.scalar(select(TrackedEntity).where(TrackedEntity.final_serial == final_serial)) is not None:
        raise APIError(409, "FINAL_SERIAL_ALREADY_EXISTS", "Финальный серийный номер уже используется")
    entity = TrackedEntity(
        qr_code=payload.qr_code,
        entity_type=payload.entity_type,
        model_id=route.model_id,
        route_version_id=route.id,
        status="IN_PROGRESS" if payload.entity_type == "WIP" else "ACTIVE",
        final_serial=final_serial,
    )
    db.add(entity)
    db.flush()
    record_audit(
        db,
        actor_user_id=context.user.id,
        action="TRACKED_ENTITY_CREATED",
        object_type="tracked_entity",
        object_id=entity.id,
        trace_id=_trace_id(request),
        after=_entity_payload(entity),
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise APIError(409, "ENTITY_IDENTIFIER_CONFLICT", "QR или финальный серийный номер уже используется") from exc
    return _entity_payload(entity)

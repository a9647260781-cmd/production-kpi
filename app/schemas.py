from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class WorkSessionRequest(BaseModel):
    shift_id: str
    row_id: str
    workstation_id: str
    route_step_id: str


class OperationEventRequest(BaseModel):
    event_id: str = Field(min_length=36, max_length=36)
    work_session_id: str
    subject_qr: str
    event_type: Literal["COMPLETE"] = "COMPLETE"
    attempt_type: Literal["PRIMARY", "REWORK"] = "PRIMARY"
    attempt_no: int = Field(default=1, ge=1, le=99)
    occurred_at_device: datetime | None = None


class PendingResolveRequest(BaseModel):
    action: Literal["CANCEL"]
    reason: str = Field(min_length=3, max_length=240)


class LocalPendingCorruptionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=240)
    fingerprint: str = Field(min_length=8, max_length=128)


class GenealogyActionRequest(BaseModel):
    request_id: str
    action: Literal["ATTACH", "DETACH", "REPLACE", "FINALIZE", "SCRAP"]
    parent_qr: str
    child_qr: str
    replacement_qr: str | None = None
    reason: str | None = Field(default=None, max_length=240)


class AssignmentRequest(BaseModel):
    employee_id: str
    row_id: str
    workstation_id: str
    route_step_id: str
    starts_at: datetime
    ends_at: datetime
    transfer_from_assignment_id: str | None = None


class TimeEntryRequest(BaseModel):
    assignment_id: str
    category: Literal["PRIMARY", "REWORK", "WAITING", "SETUP", "SUPPORT", "UNAVAILABLE"]
    hours: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    source: str = "DEMO"
    reason: str | None = None


class QualityDecisionRequest(BaseModel):
    request_id: str
    entity_qr: str
    decision: Literal["ACCEPT", "REJECT"]
    defect_code: str | None = None
    note: str | None = None


class QCInspectionRequest(BaseModel):
    inspection_id: str = Field(min_length=36, max_length=36)
    work_session_id: str
    subject_qr: str
    decision: Literal["ACCEPT", "REJECT"]
    defect_code: str | None = Field(default=None, max_length=64)
    occurred_at_device: datetime | None = None


class QualityAuditRequest(BaseModel):
    request_id: str
    decision_id: str
    result: Literal["CONFIRMED", "OVERTURNED"]
    note: str | None = None


class ReworkOrderRequest(BaseModel):
    request_id: str
    entity_qr: str
    quality_decision_id: str
    requested_route_step_id: str
    reason: str = Field(min_length=3, max_length=240)


class PlanLineRequest(BaseModel):
    key: str
    model_id: str
    route_step_id: str
    row_id: str | None = None
    planned_qty: int = Field(ge=0)
    norm_minutes: Decimal | None = Field(default=None, ge=0)


class PlanCreateRequest(BaseModel):
    shift_id: str
    status: Literal["DRAFT", "APPROVED"] = "DRAFT"
    reason: str | None = None
    mode: Literal["PATCH", "FULL"] = "PATCH"
    confirm_full_replacement: bool = False
    lines: list[PlanLineRequest]


class StandardValueRequest(BaseModel):
    route_step_id: str
    norm_minutes: Decimal = Field(gt=0)


class StandardCreateRequest(BaseModel):
    model_id: str
    status: Literal["DRAFT", "APPROVED"] = "DRAFT"
    effective_from: datetime
    reason: str | None = None
    mode: Literal["PATCH", "FULL"] = "PATCH"
    confirm_full_replacement: bool = False
    values: list[StandardValueRequest]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


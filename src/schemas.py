from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator


class RebookRequest(BaseModel):
    flight_no: str
    pax_ids: list[str]
    target_flight: str

    @field_validator("pax_ids")
    @classmethod
    def pax_ids_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("pax_ids must contain at least one passenger ID")
        return v


class ScheduleChangeRequest(BaseModel):
    flight_no: str
    change_type: str
    details: str
    controller_id: str


class CommitChangeRequest(BaseModel):
    change_id: str
    controller_id: str


class SanitiseRequest(BaseModel):
    text: str


class AuditEntry(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    event_type: str
    flight_no: Optional[str] = None
    details: str
    actor: Optional[str] = None
    model_used: Optional[str] = None
    result: str

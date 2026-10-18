from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_complete: StrictBool | None = None
    workplace_size: Literal["under5", "5plus", "unknown"] = "unknown"
    weekly_work_hours: float | None = Field(default=None, ge=0, le=168)
    event_date: date | None = None
    move_in: StrictBool | None = None
    resident_registration: StrictBool | None = None
    deposit_returned: StrictBool | None = None


class ReadingInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    methods: list[Literal["text", "pdf_text", "ocr", "manual_text"]] = Field(min_length=1, max_length=20)
    ocr_used: StrictBool = False
    warnings: list[str] = Field(default_factory=list, max_length=21)

    @model_validator(mode="after")
    def matches_methods(self):
        if self.ocr_used != ("ocr" in self.methods):
            raise ValueError("OCR 사용 표시와 읽기 방식이 일치하지 않습니다.")
        if any(len(warning) > 500 for warning in self.warnings):
            raise ValueError("읽기 안내가 너무 깁니다.")
        return self


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="내 계약서", min_length=1, max_length=120)
    text: str = Field(min_length=20, max_length=50000)
    contract_type: Literal["employment", "lease", "sale"] = "employment"
    user_role: Literal["worker", "employer", "tenant", "landlord", "buyer", "seller"] | None = None
    engine: Literal["rules", "ollama"] = "rules"
    evidence_mode: Literal["local", "live"] = "local"
    context: Context = Field(default_factory=Context)
    reading: ReadingInfo | None = None

    @model_validator(mode="after")
    def role_matches_contract(self):
        roles = {"employment": ("worker", "employer"), "lease": ("tenant", "landlord"), "sale": ("buyer", "seller")}
        if self.user_role is None:
            self.user_role = roles[self.contract_type][0]
        if self.user_role not in roles[self.contract_type]:
            raise ValueError("계약서 종류에 맞는 본인의 입장을 선택해주세요.")
        return self

    @field_validator("text")
    @classmethod
    def meaningful_text(cls, value):
        if len(value.strip()) < 20:
            raise ValueError("계약서 내용을 20자 이상 입력해주세요.")
        return value.replace("\r\n", "\n").replace("\r", "\n")


class AnswersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_revision: int = Field(ge=1)
    context: Context


class IncidentFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    writer: str = Field(default="", max_length=200)
    counterparty: str = Field(default="", max_length=200)
    date: str = Field(default="", max_length=100)
    place: str = Field(default="", max_length=300)
    summary: str = Field(default="", max_length=8000)
    loss: str = Field(default="", max_length=500)
    evidence: str = Field(default="", max_length=2000)
    desired_outcome: str = Field(default="", max_length=1000)


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_revision: int = Field(ge=1)
    kind: Literal["summary", "request", "lawyer_request", "help_request", "complaint"] = "summary"
    incident: IncidentFacts = Field(default_factory=IncidentFacts)

    @model_validator(mode="after")
    def complaint_needs_facts(self):
        if self.kind == "complaint" and len(self.incident.summary.strip()) < 20:
            raise ValueError("고소 초안에는 실제로 있었던 일을 20자 이상 입력해주세요.")
        return self


class StandaloneDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["lawyer_request", "help_request", "complaint"] = "lawyer_request"
    incident: IncidentFacts

    @model_validator(mode="after")
    def needs_facts(self):
        if len(self.incident.summary.strip()) < 20:
            raise ValueError("실제로 있었던 일을 20자 이상 입력해주세요.")
        return self


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_revision: int = Field(ge=1)
    question: str = Field(min_length=2, max_length=1500)
    finding_id: str | None = Field(default=None, max_length=20)
    intent: Literal["explain", "scenario", "rewrite", "prepare", "custom"] = "custom"

    @field_validator("question")
    @classmethod
    def meaningful_question(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("궁금한 내용을 입력해주세요.")
        return value.strip()


class TranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_revision: int = Field(ge=1)
    language: Literal["zh", "es"]

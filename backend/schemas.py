import re
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


Language = Literal["ko", "zh", "es"]


class ReadPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1, le=20)
    text: str = Field(max_length=50000)
    method: Literal["text", "pdf_text", "ocr", "openai_vision", "manual_text"]
    status: Literal["ok", "needs_review", "failed"] = "ok"
    warnings: list[str] = Field(default_factory=list, max_length=20)
    confirmed: StrictBool = False
    error_code: str | None = None


class ReadingInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    methods: list[Literal["text", "pdf_text", "ocr", "manual_text", "openai_vision"]] = Field(min_length=1, max_length=20)
    ocr_used: StrictBool = False
    pages: list[ReadPage] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=21)

    @model_validator(mode="after")
    def matches_methods(self):
        if self.ocr_used != ("ocr" in self.methods or "openai_vision" in self.methods):
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
    engine: Literal["rules", "ollama", "openai"] = "rules"
    language: Language = "ko"
    evidence_mode: Literal["local", "live"] = "local"
    context: Context = Field(default_factory=Context)
    reading: ReadingInfo | None = None
    document_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")

    @model_validator(mode="after")
    def role_matches_contract(self):
        roles = {"employment": ("worker", "employer"), "lease": ("tenant", "landlord"), "sale": ("buyer", "seller")}
        if self.user_role is None:
            self.user_role = roles[self.contract_type][0]
        if self.user_role not in roles[self.contract_type]:
            raise ValueError("계약서 종류에 맞는 본인의 입장을 선택해주세요.")
        if self.reading and self.reading.pages:
            pages = self.reading.pages
            if [p.page for p in pages] != list(range(1, len(pages) + 1)):
                raise ValueError("페이지 순서를 확인해주세요.")
            if any(not p.confirmed or p.status == "failed" or not p.text.strip() or "[판독 불가]" in p.text for p in pages):
                raise ValueError("모든 페이지의 판독 결과를 확인·수정한 뒤 확인 표시를 해주세요.")
            if self.text != "\f".join(p.text for p in pages):
                raise ValueError("확인한 페이지와 검토할 원문이 일치하지 않습니다.")
        if len(self.text.split("\f")) > 20:
            raise ValueError("문서는 20페이지까지 지원합니다.")
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
    language: Language = "ko"
    incident_original: IncidentFacts | None = None
    incident_confirmed: StrictBool = False
    kind: Literal["summary", "request", "revision_request", "lawyer_request", "help_request", "complaint"] = "summary"
    incident: IncidentFacts = Field(default_factory=IncidentFacts)
    finding_ids: list[str] | None = Field(default=None, max_length=100)
    written_on: str = Field(default="", max_length=40)
    reply_by: str = Field(default="", max_length=40)

    @model_validator(mode="after")
    def complaint_needs_facts(self):
        if (self.language != "ko" or any(re.search(r"[A-Za-z一-鿿]", v) and not re.search(r"[가-힣]", v) for k, v in self.incident.model_dump().items() if k in {"summary", "loss", "evidence", "desired_outcome"})) and any(self.incident.model_dump().values()) and not self.incident_confirmed:
            raise ValueError("사건 경위의 한국어 해석을 확인한 뒤 문서에 반영해주세요.")
        if self.kind == "complaint" and len(self.incident.summary.strip()) < 20:
            raise ValueError("고소 초안에는 실제로 있었던 일을 20자 이상 입력해주세요.")
        return self


class DocumentPdfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="문서", max_length=200)
    text: str = Field(min_length=1, max_length=50000)


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
    language: Language = "ko"
    engine: Literal["ollama", "openai"] = "ollama"
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

    engine: Literal["template", "openai"] = "template"


class AutoTranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_revision: int = Field(ge=1)
    language: Literal["zh", "es"]


class DocumentTranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_revision: int = Field(ge=1)
    language: Literal["zh", "es"]
    text: str = Field(min_length=1, max_length=50000)


class IncidentTranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_revision: int = Field(ge=1)
    language: Language
    incident: IncidentFacts

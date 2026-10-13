from typing import List, Optional, Union
from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    page: Optional[Union[int, str]] = None
    text: str
    score: Optional[float] = None
    chunk_id: Optional[str] = None


class DeviceCard(BaseModel):
    name: str
    product_code: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    tasks: List[str] = Field(default_factory=list)
    matched_reason: str = ""
    fit_tags: List[str] = Field(default_factory=list)
    selection_notes: List[str] = Field(default_factory=list)
    source_pages: List[Union[int, str]] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)


class ClarifyingQuestion(BaseModel):
    id: str
    question: str
    options: List[str] = Field(default_factory=list)


class AgentAnswer(BaseModel):
    intent: str
    answer: str
    recommended_devices: List[DeviceCard] = Field(default_factory=list)
    need_more_info: List[str] = Field(default_factory=list)
    clarifying_questions: List[ClarifyingQuestion] = Field(default_factory=list)
    related_questions: List[str] = Field(default_factory=list)
    disclaimer: str = "内容由AI生成，仅供参考。"

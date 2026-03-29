from pydantic import BaseModel, Field


class DetectRequest(BaseModel):
    text: str = Field(..., max_length=512_000)
    language: str = Field(default="auto")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    entities: list[str] | None = None
    allow_list: list[str] | None = None


class EntityDetail(BaseModel):
    entity_type: str
    start: int
    end: int
    score: float


class DetectResponse(BaseModel):
    has_pii: bool
    entity_count: int
    entities_found: list[str]
    language_detected: str
    language_confidence: float | None = None


class DetectDetailedResponse(DetectResponse):
    details: list[EntityDetail]

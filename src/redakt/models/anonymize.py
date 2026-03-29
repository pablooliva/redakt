from pydantic import BaseModel, Field


class AnonymizeRequest(BaseModel):
    text: str = Field(..., max_length=512_000)
    language: str = Field(default="auto")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    entities: list[str] | None = None
    allow_list: list[str] | None = None


class AnonymizeResponse(BaseModel):
    anonymized_text: str
    mappings: dict[str, str]
    language_detected: str
    language_confidence: float | None = None

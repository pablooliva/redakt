from pydantic import BaseModel, Field


class DeanonymizeRequest(BaseModel):
    text: str = Field(..., max_length=512_000)
    mappings: dict[str, str] = Field(
        ...,
        description="Placeholder-to-original mapping returned by /api/anonymize",
    )


class DeanonymizeResponse(BaseModel):
    text: str
    replacements_made: int

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str
    presidio_analyzer: str
    presidio_anonymizer: str

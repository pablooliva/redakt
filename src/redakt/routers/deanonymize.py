from fastapi import APIRouter

from redakt.models.deanonymize import DeanonymizeRequest, DeanonymizeResponse

router = APIRouter(prefix="/api", tags=["deanonymization"])


def apply_mappings(text: str, mappings: dict[str, str]) -> tuple[str, int]:
    """Replace placeholders with original values, longest-first to avoid partial matches."""
    if not mappings:
        return text, 0

    replacements_made = 0
    # Sort by placeholder length descending to prevent partial-match corruption
    # e.g., <PERSON_10> must be replaced before <PERSON_1>
    for placeholder in sorted(mappings, key=len, reverse=True):
        original = mappings[placeholder]
        count = text.count(placeholder)
        if count > 0:
            text = text.replace(placeholder, original)
            replacements_made += count

    return text, replacements_made


@router.post("/deanonymize")
async def deanonymize(body: DeanonymizeRequest) -> DeanonymizeResponse:
    restored_text, replacements_made = apply_mappings(body.text, body.mappings)
    return DeanonymizeResponse(text=restored_text, replacements_made=replacements_made)

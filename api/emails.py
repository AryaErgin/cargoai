"""Email intake prepares text for the existing reviewed RFQ workflow."""
from fastapi import APIRouter, HTTPException, Request
from app.email_intake import MAX_EMAIL_BYTES, decode_email

router = APIRouter(prefix="/email", tags=["Email intake"])


@router.post("/decode")
async def decode(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_EMAIL_BYTES:
            raise HTTPException(413, "Email must be at most 1 MB.")
        raw.extend(chunk)
    try:
        return decode_email(bytes(raw))
    except (ValueError, LookupError, UnicodeError):
        raise HTTPException(400, "Email could not be read. Use a valid .eml with a nonempty text body of at most 20,000 characters.") from None

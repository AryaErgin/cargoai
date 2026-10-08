"""Decode a bounded .eml message without processing attachments."""
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser

MAX_EMAIL_BYTES = 1_000_000


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "li", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag in {"p", "div", "li", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def decode_email(raw: bytes) -> dict:
    if not raw or len(raw) > MAX_EMAIL_BYTES:
        raise ValueError("Email must be nonempty and at most 1 MB.")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if not any(message.get(key) for key in ("From", "Subject", "To")):
        raise ValueError("Upload a valid .eml email with message headers.")
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None or part.get_content_disposition() == "attachment":
        raise ValueError("Email has no readable text body.")
    body = part.get_content()
    if not isinstance(body, str):
        raise ValueError("Email has no readable text body.")
    if part.get_content_type() == "text/html":
        parser = VisibleText()
        parser.feed(body)
        body = "".join(parser.parts)
    subject = str(message.get("Subject", ""))
    text = f"Subject: {subject}\n\n{body.strip()}"
    if not body.strip():
        raise ValueError("Email has an empty body.")
    if len(text) > 20_000:
        raise ValueError("Email text must be at most 20,000 characters.")
    return {"subject": subject, "sender": str(message.get("From", "")), "text": text,
            "attachments_ignored": sum(1 for _ in message.iter_attachments())}

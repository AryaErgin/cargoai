import unittest
from email.message import EmailMessage
from app.email_intake import decode_email


class EmailIntakeTests(unittest.TestCase):
    def test_plain_body_preferred_and_attachments_ignored(self):
        message = EmailMessage()
        message["From"] = "customer@example.com"
        message["Subject"] = "Shanghai quotation"
        message.set_content("Please quote 2x40HC Shanghai to Ambarli.")
        message.add_alternative("<p>Alternative body</p>", subtype="html")
        message.add_attachment(b"private data", maintype="application", subtype="pdf", filename="request.pdf")
        result = decode_email(message.as_bytes())
        self.assertIn("2x40HC", result["text"])
        self.assertNotIn("Alternative body", result["text"])
        self.assertNotIn("private data", result["text"])
        self.assertEqual(result["attachments_ignored"], 1)

    def test_html_converted_to_text(self):
        raw = b"Subject: Quote\nContent-Type: text/html; charset=utf-8\n\n<p>Shanghai &amp; Ambarli</p><script>hidden</script><p>2x40HC</p>"
        result = decode_email(raw)
        self.assertIn("Shanghai & Ambarli", result["text"])
        self.assertNotIn("hidden", result["text"])
        self.assertNotIn("<p>", result["text"])

    def test_invalid_empty_and_oversized_messages(self):
        for raw in (b"", b"not an email", b"Subject: Quote\n\n", b"x" * 1_000_001,
                    b"Subject: Quote\n\n" + b"x" * 20_001):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                decode_email(raw)

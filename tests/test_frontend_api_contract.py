import unittest

from fastapi.testclient import TestClient

from api.main import app


class FrontendApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_returns_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_empty_and_oversized_text_return_400(self):
        empty = self.client.post("/parse/spot", json={"text": "  "})
        too_long = self.client.post("/parse/tender", json={"text": "x" * 20001})
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(too_long.status_code, 400)

    def test_cors_allows_only_configured_frontend(self):
        allowed = self.client.options(
            "/parse/spot",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        denied = self.client.options(
            "/parse/spot",
            headers={
                "Origin": "http://example.invalid",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(
            allowed.headers.get("access-control-allow-origin"),
            "http://localhost:3000",
        )
        self.assertNotIn("access-control-allow-origin", denied.headers)


if __name__ == "__main__":
    unittest.main()

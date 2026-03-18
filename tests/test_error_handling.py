import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.routers.auth import login_sessions


class ErrorHandlingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        login_sessions.clear()

    def test_http_errors_return_unified_payload(self) -> None:
        response = self.client.get("/auth/session/missing-session")

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["detail"], "会话不存在或已失效")
        self.assertEqual(payload["error_code"], "SESSION_NOT_FOUND")
        self.assertEqual(payload["path"], "/auth/session/missing-session")
        self.assertIn("timestamp", payload)

    def test_validation_errors_return_structured_details(self) -> None:
        response = self.client.post("/auth/logout", json={})

        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertEqual(payload["detail"], "请求参数不合法")
        self.assertEqual(payload["error_code"], "VALIDATION_ERROR")
        self.assertEqual(payload["path"], "/auth/logout")
        self.assertIsInstance(payload["details"], list)

    def test_unhandled_errors_return_internal_error_payload(self) -> None:
        with patch("app.routers.auth.get_session", side_effect=RuntimeError("boom")):
            response = self.client.get("/auth/session/force-error")

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertEqual(payload["detail"], "服务器内部错误，请查看日志")
        self.assertEqual(payload["error_code"], "INTERNAL_SERVER_ERROR")
        self.assertEqual(payload["path"], "/auth/session/force-error")

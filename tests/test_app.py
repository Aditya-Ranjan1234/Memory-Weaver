from __future__ import annotations

import io
import os
import re
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


TEST_DB = Path(tempfile.gettempdir()) / f"memory_weaver_test_{os.getpid()}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["MW_DEV_AUTH"] = "1"
os.environ["MW_SESSION_SECRET"] = "test-session-secret"
os.environ["OPENAI_API_KEY"] = "test-key"

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from memory_weaver.database import engine  # noqa: E402


class FakeOpenAI:
    def __init__(self) -> None:
        self.responses = SimpleNamespace(create=self._respond)
        self.audio = SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=lambda **_: SimpleNamespace(text="A spoken memory")
            )
        )
        self.response_number = 0

    def _respond(self, **_: object) -> SimpleNamespace:
        self.response_number += 1
        if self.response_number == 1:
            text = (
                "That first school morning sounds vivid. Who walked with you that day?"
            )
        elif self.response_number == 2:
            text = "Your grandmother being beside you feels important. What do you remember seeing?"
        else:
            text = (
                '{"title":"My First School Morning","content":"I walked to school with my '
                'grandmother.","tags":["school","grandmother"],"year":null}'
            )
        return SimpleNamespace(output_text=text)


class MemoryWeaverTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        engine.dispose()
        TEST_DB.unlink(missing_ok=True)

    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        login_page = self.client.get("/login")
        token_match = re.search(
            r'<meta name="csrf-token" content="([^"]+)"', login_page.text
        )
        self.assertIsNotNone(token_match)
        response = self.client.post(
            "/api/dev-login",
            headers={"X-CSRF-Token": token_match.group(1)},
        )
        self.assertEqual(response.status_code, 200)
        app_page = self.client.get("/app")
        token_match = re.search(
            r'<meta name="csrf-token" content="([^"]+)"', app_page.text
        )
        self.assertIsNotNone(token_match)
        self.csrf_headers = {"X-CSRF-Token": token_match.group(1)}

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def test_story_and_invite_flow(self) -> None:
        response = self.client.post(
            "/api/stories",
            headers=self.csrf_headers,
            json={
                "kind": "timeline_event",
                "title": "First day",
                "content": "Grandmother walked me to school.",
                "tags": ["school", "family"],
                "year": 1970,
            },
        )
        self.assertEqual(response.status_code, 200)
        story_id = response.json()["id"]

        stories = self.client.get("/api/stories?scope=me").json()["stories"]
        self.assertTrue(any(story["id"] == story_id for story in stories))
        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertGreaterEqual(dashboard.json()["counts"]["timeline"], 1)

        invite = self.client.post("/api/family/invite", headers=self.csrf_headers)
        self.assertEqual(invite.status_code, 200)
        self.assertGreater(invite.json()["expires_at"], 0)
        token = invite.json()["url"].split("#", 1)[1]
        self.assertEqual(
            self.client.post(
                "/api/family/accept",
                headers=self.csrf_headers,
                json={"token": token},
            ).status_code,
            400,
        )

    def test_security_headers_and_csrf(self) -> None:
        response = self.client.get("/app")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn(
            "frame-ancestors 'none'", response.headers["content-security-policy"]
        )
        rejected = self.client.post(
            "/api/stories",
            json={"title": "Blocked", "content": "Missing CSRF token", "tags": []},
        )
        self.assertEqual(rejected.status_code, 403)

    @patch("memory_weaver.app.get_openai_client")
    def test_voice_and_interview_flow(self, openai_client) -> None:
        fake = FakeOpenAI()
        openai_client.return_value = fake

        audio = io.BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\x00\x00" * 800)
        transcription = self.client.post(
            "/api/transcribe",
            headers=self.csrf_headers,
            files={"audio": ("memory.wav", audio.getvalue(), "audio/wav")},
        )
        self.assertEqual(transcription.status_code, 200)
        self.assertEqual(transcription.json()["text"], "A spoken memory")

        started = self.client.post(
            "/api/interviews",
            headers=self.csrf_headers,
            json={"topic": "first school day"},
        )
        self.assertEqual(started.status_code, 200)
        interview_id = started.json()["interview_id"]

        continued = self.client.post(
            f"/api/interviews/{interview_id}/messages",
            headers=self.csrf_headers,
            json={"message": "My grandmother walked with me."},
        )
        self.assertEqual(continued.status_code, 200)

        finalized = self.client.post(
            f"/api/interviews/{interview_id}/finalize",
            headers=self.csrf_headers,
        )
        self.assertEqual(finalized.status_code, 200)
        self.assertEqual(finalized.json()["story"]["title"], "My First School Morning")


if __name__ == "__main__":
    unittest.main()

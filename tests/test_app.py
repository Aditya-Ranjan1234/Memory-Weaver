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
os.environ["MW_GOOGLE_CLIENT_ID"] = "test-client.apps.googleusercontent.com"

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
        login_token = self._csrf_from(self.client, "/login")
        response = self.client.post(
            "/api/dev-login",
            headers={"X-CSRF-Token": login_token},
        )
        self.assertEqual(response.status_code, 200)
        self.csrf_headers = {"X-CSRF-Token": self._csrf_from(self.client, "/app")}

    def _csrf_from(self, client: TestClient, path: str) -> str:
        page = client.get(path)
        self.assertEqual(page.status_code, 200)
        token_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
        self.assertIsNotNone(token_match)
        return token_match.group(1)

    def _google_login(
        self,
        client: TestClient,
        *,
        sub: str,
        email: str,
        name: str,
    ) -> dict[str, str]:
        login_token = self._csrf_from(client, "/login")
        identity = {
            "sub": sub,
            "email": email,
            "email_verified": True,
            "name": name,
            "picture": "https://example.com/avatar.png",
        }
        with patch(
            "memory_weaver.app.google_id_token.verify_oauth2_token",
            return_value=identity,
        ):
            response = client.post(
                "/api/auth/google",
                headers={"X-CSRF-Token": login_token},
                json={"credential": f"fake-google-token-{sub}"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["email"], email)
        return {"X-CSRF-Token": self._csrf_from(client, "/app")}

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

    def test_logout_ends_authenticated_session(self) -> None:
        response = self.client.post("/api/logout", headers=self.csrf_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/stories").status_code, 401)

    def test_all_pages_and_static_assets(self) -> None:
        anonymous = TestClient(app)
        expected = {
            "/": "text/html",
            "/index.html": "text/html",
            "/login": "text/html",
            "/app": "text/html",
            "/invite": "text/html",
            "/favicon.svg": "image/svg+xml",
            "/favicon.ico": "image/svg+xml",
            "/manifest.webmanifest": "application/manifest+json",
            "/sw.js": "application/javascript",
            "/health": "application/json",
        }
        for path, content_type in expected.items():
            with self.subTest(path=path):
                client = self.client if path == "/app" else anonymous
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(content_type, response.headers["content-type"])

        landing = anonymous.get("/").text
        self.assertIn('class="auth-link" href="/login">Sign in</a>', landing)
        self.assertNotIn("Live build", landing)
        self.assertNotIn("demo", landing.lower())

        login = anonymous.get("/login").text
        self.assertNotIn("MW_GOOGLE_CLIENT_ID", login)
        self.assertNotIn("third-party scripts", login)
        self.assertIn("Your archive is private by default", login)

        private_app = self.client.get("/app").text
        self.assertIn('id="logoutBtn"', private_app)
        self.assertNotIn("OpenAI", private_app)
        self.assertEqual(
            self.client.get("/login", follow_redirects=False).headers["location"],
            "/app",
        )

        with (
            patch("memory_weaver.app.GOOGLE_CLIENT_ID", ""),
            patch("memory_weaver.app.LOCAL_DEV_AUTH", False),
        ):
            unavailable = anonymous.get("/login")
        self.assertEqual(unavailable.status_code, 200)
        self.assertIn("Sign-in is taking a short pause", unavailable.text)
        self.assertNotIn("MW_GOOGLE_CLIENT_ID", unavailable.text)

        service_worker = self.client.get("/sw.js").text
        self.assertIn('const CACHE_NAME = "memory-weaver-v4"', service_worker)
        self.assertIn("!STATIC_PATHS.has(url.pathname)", service_worker)
        self.assertIn('url.pathname === "/"', service_worker)

        self.assertEqual(
            anonymous.get("/app", follow_redirects=False).status_code,
            307,
        )
        self.assertEqual(anonymous.get("/api/stories").status_code, 401)

    def test_google_accounts_connect_family_archives(self) -> None:
        with TestClient(app) as inviter, TestClient(app) as relative:
            inviter_headers = self._google_login(
                inviter,
                sub="google-user-one",
                email="one@example.test",
                name="Asha",
            )
            relative_headers = self._google_login(
                relative,
                sub="google-user-two",
                email="two@example.test",
                name="Ravi",
            )

            first_story = inviter.post(
                "/api/stories",
                headers=inviter_headers,
                json={
                    "title": "Asha's memory",
                    "content": "A story visible to connected family.",
                    "tags": ["family"],
                },
            )
            second_story = relative.post(
                "/api/stories",
                headers=relative_headers,
                json={
                    "title": "Ravi's memory",
                    "content": "Another story in the shared archive.",
                    "tags": ["family"],
                },
            )
            self.assertEqual(first_story.status_code, 200)
            self.assertEqual(second_story.status_code, 200)

            invite = inviter.post("/api/family/invite", headers=inviter_headers)
            self.assertEqual(invite.status_code, 200)
            token = invite.json()["url"].split("#", 1)[1]
            accepted = relative.post(
                "/api/family/accept",
                headers=relative_headers,
                json={"token": token},
            )
            self.assertEqual(accepted.status_code, 200)

            inviter_family = inviter.get("/api/family").json()["family"]
            relative_family = relative.get("/api/family").json()["family"]
            self.assertEqual([member["name"] for member in inviter_family], ["Ravi"])
            self.assertEqual([member["name"] for member in relative_family], ["Asha"])

            shared_titles = {
                story["title"]
                for story in inviter.get("/api/stories").json()["stories"]
            }
            own_titles = {
                story["title"]
                for story in inviter.get("/api/stories?scope=me").json()["stories"]
            }
            self.assertIn("Asha's memory", shared_titles)
            self.assertIn("Ravi's memory", shared_titles)
            self.assertIn("Asha's memory", own_titles)
            self.assertNotIn("Ravi's memory", own_titles)
            self.assertEqual(
                inviter.get("/api/dashboard").json()["counts"]["family"], 1
            )

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

from __future__ import annotations

import base64
import io
import os
import re
import tempfile
import unittest
import wave
import zipfile
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


PNG_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nQAAAABJRU5ErkJggg=="
)


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
            text = "When you picture that school morning, who was walking beside you?"
        elif self.response_number == 2:
            text = "As you walked with your grandmother, what could you see around you?"
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
        self.assertIn(
            "img-src 'self' data: blob: https:",
            response.headers["content-security-policy"],
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
        self.assertIn('id="storyImage"', private_app)
        self.assertIn('id="interviewChat"', private_app)
        self.assertIn("Reply naturally...", private_app)
        self.assertNotIn("I'm really looking forward", private_app)
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
        self.assertIn('const CACHE_NAME = "memory-weaver-v5"', service_worker)
        self.assertIn('url.pathname === "/app"', service_worker)
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

    def test_private_story_image_upload_and_validation(self) -> None:
        created = self.client.post(
            "/api/stories/with-image",
            headers=self.csrf_headers,
            data={
                "kind": "timeline_event",
                "title": "The red bicycle",
                "content": "I learned to ride it in the lane behind our home.",
                "tags": "childhood, bicycle",
                "year": "1984",
            },
            files={"image": ("bicycle.png", PNG_PIXEL, "image/png")},
        )
        self.assertEqual(created.status_code, 200)
        story_id = created.json()["id"]

        own_stories = self.client.get("/api/stories?scope=me").json()["stories"]
        saved = next(story for story in own_stories if story["id"] == story_id)
        self.assertEqual(saved["tags"], ["childhood", "bicycle"])
        self.assertEqual(saved["image_url"], f"/api/stories/{story_id}/image")

        image = self.client.get(saved["image_url"])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/png")
        self.assertEqual(image.headers["cache-control"], "private, max-age=3600")
        self.assertEqual(image.content, PNG_PIXEL)

        invalid = self.client.post(
            "/api/stories/with-image",
            headers=self.csrf_headers,
            data={"title": "Must not survive", "content": "Invalid image."},
            files={"image": ("fake.png", b"not-an-image", "image/png")},
        )
        self.assertEqual(invalid.status_code, 415)
        titles = {
            story["title"]
            for story in self.client.get("/api/stories?scope=me").json()["stories"]
        }
        self.assertNotIn("Must not survive", titles)

        bad_year = self.client.post(
            "/api/stories/with-image",
            headers=self.csrf_headers,
            data={"title": "Bad year", "content": "Invalid year.", "year": "later"},
            files={"image": ("photo.png", PNG_PIXEL, "image/png")},
        )
        self.assertEqual(bad_year.status_code, 422)
        self.assertEqual(bad_year.json()["detail"], "Enter a valid year.")

    def test_story_images_are_shared_only_with_connected_family(self) -> None:
        with (
            TestClient(app) as owner,
            TestClient(app) as relative,
            TestClient(app) as stranger,
        ):
            owner_headers = self._google_login(
                owner, sub="photo-owner", email="owner@example.test", name="Mira"
            )
            relative_headers = self._google_login(
                relative,
                sub="photo-relative",
                email="relative@example.test",
                name="Kiran",
            )
            self._google_login(
                stranger,
                sub="photo-stranger",
                email="stranger@example.test",
                name="Noor",
            )
            created = owner.post(
                "/api/stories/with-image",
                headers=owner_headers,
                data={"title": "Private photograph", "content": "For family only."},
                files={"image": ("family.png", PNG_PIXEL, "image/png")},
            )
            self.assertEqual(created.status_code, 200)
            story_id = created.json()["id"]
            image_url = f"/api/stories/{story_id}/image"
            self.assertEqual(relative.get(image_url).status_code, 404)
            self.assertEqual(stranger.get(image_url).status_code, 404)

            invite = owner.post("/api/family/invite", headers=owner_headers).json()
            token = invite["url"].split("#", 1)[1]
            accepted = relative.post(
                "/api/family/accept",
                headers=relative_headers,
                json={"token": token},
            )
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(relative.get(image_url).content, PNG_PIXEL)
            self.assertEqual(stranger.get(image_url).status_code, 404)
            self.assertEqual(
                relative.post(
                    image_url,
                    headers=relative_headers,
                    files={"image": ("replacement.png", PNG_PIXEL, "image/png")},
                ).status_code,
                404,
            )

    def test_story_revision_delete_and_restore_flow(self) -> None:
        created = self.client.post(
            "/api/stories",
            headers=self.csrf_headers,
            json={
                "title": "Original title",
                "content": "The first version of this memory.",
                "tags": ["family"],
                "year": 1988,
                "location": "Mysuru",
                "language": "English",
            },
        )
        self.assertEqual(created.status_code, 200)
        story_id = created.json()["id"]

        edited = self.client.patch(
            f"/api/archive/stories/{story_id}",
            headers=self.csrf_headers,
            json={
                "kind": "memory",
                "title": "Revised title",
                "content": "The corrected and fuller version.",
                "tags": ["family", "childhood"],
                "year": 1988,
                "location": "Mysuru",
                "latitude": 12.2958,
                "longitude": 76.6394,
                "language": "English",
            },
        )
        self.assertEqual(edited.status_code, 200)
        revisions = self.client.get(
            f"/api/archive/stories/{story_id}/revisions"
        ).json()["revisions"]
        self.assertEqual(revisions[0]["title"], "Original title")

        deleted = self.client.delete(
            f"/api/archive/stories/{story_id}", headers=self.csrf_headers
        )
        self.assertEqual(deleted.status_code, 200)
        visible_ids = {
            story["id"] for story in self.client.get("/api/stories").json()["stories"]
        }
        self.assertNotIn(story_id, visible_ids)
        trash_ids = {
            story["id"]
            for story in self.client.get("/api/archive/stories/deleted").json()[
                "stories"
            ]
        }
        self.assertIn(story_id, trash_ids)
        restored = self.client.post(
            f"/api/archive/stories/{story_id}/restore", headers=self.csrf_headers
        )
        self.assertEqual(restored.status_code, 200)

        restore_version = self.client.post(
            f"/api/archive/stories/{story_id}/revisions/{revisions[0]['id']}/restore",
            headers=self.csrf_headers,
        )
        self.assertEqual(restore_version.status_code, 200)
        saved = next(
            story
            for story in self.client.get("/api/stories").json()["stories"]
            if story["id"] == story_id
        )
        self.assertEqual(saved["title"], "Original title")

    def test_editor_role_controls_cross_family_changes(self) -> None:
        with TestClient(app) as owner, TestClient(app) as relative:
            owner_headers = self._google_login(
                owner, sub="role-owner", email="owner-role@example.test", name="Owner"
            )
            relative_headers = self._google_login(
                relative,
                sub="role-relative",
                email="relative-role@example.test",
                name="Editor",
            )
            story_id = owner.post(
                "/api/stories",
                headers=owner_headers,
                json={"title": "Owner story", "content": "Owner's original words."},
            ).json()["id"]
            token = (
                owner.post("/api/family/invite", headers=owner_headers)
                .json()["url"]
                .split("#", 1)[1]
            )
            self.assertEqual(
                relative.post(
                    "/api/family/accept",
                    headers=relative_headers,
                    json={"token": token},
                ).status_code,
                200,
            )
            blocked = relative.patch(
                f"/api/archive/stories/{story_id}",
                headers=relative_headers,
                json={
                    "kind": "memory",
                    "title": "Blocked edit",
                    "content": "A contributor cannot rewrite the owner's memory.",
                    "tags": [],
                },
            )
            self.assertEqual(blocked.status_code, 404)
            relative_id = relative.get("/api/me").json()["user"]["id"]
            role_change = owner.patch(
                f"/api/archive/family/{relative_id}/role",
                headers=owner_headers,
                json={"role": "editor"},
            )
            self.assertEqual(role_change.status_code, 200)
            allowed = relative.patch(
                f"/api/archive/stories/{story_id}",
                headers=relative_headers,
                json={
                    "kind": "memory",
                    "title": "Family-edited story",
                    "content": "An editor added a verified detail.",
                    "tags": ["family"],
                },
            )
            self.assertEqual(allowed.status_code, 200)
            owner_story = next(
                story
                for story in owner.get("/api/stories").json()["stories"]
                if story["id"] == story_id
            )
            self.assertEqual(owner_story["title"], "Family-edited story")

    def test_archive_platform_features_and_exports(self) -> None:
        story = self.client.post(
            "/api/stories",
            headers=self.csrf_headers,
            json={
                "kind": "timeline_event",
                "title": "Festival courtyard",
                "content": "Everyone gathered near the lamps after sunset.",
                "tags": ["festival", "family"],
                "year": 1999,
                "location": "Mysuru",
                "latitude": 12.2958,
                "longitude": 76.6394,
            },
        )
        story_id = story.json()["id"]
        person = self.client.post(
            "/api/archive/people",
            headers=self.csrf_headers,
            json={"name": "Lakshmi", "relation": "Grandmother", "birth_year": 1940},
        )
        self.assertEqual(person.status_code, 200)
        person_id = person.json()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/archive/stories/{story_id}/people/{person_id}",
                headers=self.csrf_headers,
            ).status_code,
            200,
        )

        media = self.client.post(
            f"/api/archive/stories/{story_id}/media",
            headers=self.csrf_headers,
            data={"caption": "Courtyard lamps", "location": "Mysuru"},
            files={"file": ("lamps.png", PNG_PIXEL, "image/png")},
        )
        self.assertEqual(media.status_code, 200)
        media_id = media.json()["id"]
        self.assertEqual(
            self.client.get(f"/api/archive/media/{media_id}").content, PNG_PIXEL
        )
        audio_media = self.client.post(
            f"/api/archive/stories/{story_id}/media",
            headers=self.csrf_headers,
            data={"transcript": "The bells rang after sunset."},
            files={"file": ("memory.webm", b"synthetic-audio", "audio/webm")},
        )
        self.assertEqual(audio_media.status_code, 200)
        self.assertEqual(audio_media.json()["kind"], "audio")

        album = self.client.post(
            "/api/archive/albums",
            headers=self.csrf_headers,
            json={"title": "Festival album", "description": "Family celebrations"},
        )
        album_id = album.json()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/archive/albums/{album_id}/items",
                headers=self.csrf_headers,
                json={"media_id": media_id},
            ).status_code,
            200,
        )
        albums = self.client.get("/api/archive/albums").json()["albums"]
        self.assertTrue(any(item["media"] for item in albums if item["id"] == album_id))

        capsule = self.client.post(
            "/api/archive/capsules",
            headers=self.csrf_headers,
            json={
                "title": "Open next year",
                "content": "Remember the courtyard lights.",
                "recipient_user_id": None,
                "unlock_at": 4102444800,
            },
        )
        self.assertEqual(capsule.status_code, 200)
        self.assertTrue(self.client.get("/api/archive/capsules").json()["capsules"])

        self.assertEqual(
            self.client.post(
                f"/api/archive/stories/{story_id}/comments",
                headers=self.csrf_headers,
                json={"content": "I remember those lamps."},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.put(
                f"/api/archive/stories/{story_id}/reaction",
                headers=self.csrf_headers,
                json={"emoji": "heart"},
            ).status_code,
            200,
        )
        social = self.client.get(f"/api/archive/stories/{story_id}/social").json()
        self.assertEqual(social["comments"][0]["content"], "I remember those lamps.")
        self.assertEqual(social["reactions"]["heart"], 1)

        draft = {"title": "Autosaved", "content": "Still writing"}
        self.assertEqual(
            self.client.put(
                "/api/archive/drafts/story-composer",
                headers=self.csrf_headers,
                json={"payload": draft},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/api/archive/drafts/story-composer").json()["payload"],
            draft,
        )
        search = self.client.get(
            "/api/archive/search?q=courtyard&location=Mysuru&year_from=1999&year_to=1999"
        ).json()["stories"]
        self.assertTrue(any(item["id"] == story_id for item in search))

        exported = self.client.get("/api/archive/account/export")
        self.assertEqual(exported.status_code, 200)
        self.assertTrue(
            any(item["id"] == story_id for item in exported.json()["stories"])
        )
        archive = self.client.get("/api/archive/account/export.zip")
        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(archive.content)) as exported_zip:
            self.assertIn("memory-weaver-data.json", exported_zip.namelist())
            self.assertTrue(
                any(name.startswith("media/") for name in exported_zip.namelist())
            )
        storybook = self.client.get("/api/archive/storybook.pdf")
        self.assertEqual(storybook.status_code, 200)
        self.assertTrue(storybook.content.startswith(b"%PDF"))

    @patch("memory_weaver.app.get_openai_client")
    def test_collaborative_interview_access(self, openai_client) -> None:
        openai_client.return_value = FakeOpenAI()
        with TestClient(app) as owner, TestClient(app) as relative:
            owner_headers = self._google_login(
                owner,
                sub="interview-owner",
                email="interview-owner@example.test",
                name="Anita",
            )
            relative_headers = self._google_login(
                relative,
                sub="interview-relative",
                email="interview-relative@example.test",
                name="Dev",
            )
            token = (
                owner.post("/api/family/invite", headers=owner_headers)
                .json()["url"]
                .split("#", 1)[1]
            )
            relative.post(
                "/api/family/accept",
                headers=relative_headers,
                json={"token": token},
            )
            started = owner.post(
                "/api/interviews",
                headers=owner_headers,
                json={"topic": "our first family home"},
            )
            interview_id = started.json()["interview_id"]
            relative_id = relative.get("/api/me").json()["user"]["id"]
            invited = owner.post(
                f"/api/archive/interviews/{interview_id}/participants",
                headers=owner_headers,
                json={"user_id": relative_id},
            )
            self.assertEqual(invited.status_code, 200)
            shared = relative.get(f"/api/archive/interviews/{interview_id}")
            self.assertEqual(shared.status_code, 200)
            continued = relative.post(
                f"/api/interviews/{interview_id}/messages",
                headers=relative_headers,
                json={"message": "I remember the blue front door."},
            )
            self.assertEqual(continued.status_code, 200)
            listed_ids = {
                item["id"]
                for item in relative.get("/api/archive/interviews").json()["interviews"]
            }
            self.assertIn(interview_id, listed_ids)

    def test_account_deletion_ends_session(self) -> None:
        with TestClient(app) as account:
            headers = self._google_login(
                account,
                sub="delete-account-user",
                email="delete-me@example.test",
                name="Delete Me",
            )
            account.post(
                "/api/stories",
                headers=headers,
                json={"title": "Temporary", "content": "This will be deleted."},
            )
            deleted = account.request(
                "DELETE",
                "/api/archive/account",
                headers=headers,
                json={"confirmation": "DELETE MY ARCHIVE"},
            )
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(account.get("/api/me").status_code, 401)

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
            files={
                "audio": (
                    "memory.webm",
                    audio.getvalue(),
                    "audio/webm;codecs=opus",
                )
            },
        )
        self.assertEqual(transcription.status_code, 200)
        self.assertEqual(transcription.json()["text"], "A spoken memory")

        started = self.client.post(
            "/api/interviews",
            headers=self.csrf_headers,
            json={"topic": "first school day"},
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["reply"].count("?"), 1)
        self.assertNotIn("looking forward", started.json()["reply"].lower())
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

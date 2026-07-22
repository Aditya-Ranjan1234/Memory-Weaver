from __future__ import annotations

import hashlib
import hmac
import html as html_lib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

# Google token verification
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from memory_weaver.database import (
    FamilyLink,
    InterviewMessage,
    InterviewSession,
    Invite,
    RateLimitEvent,
    Story,
    StoryImage,
    User,
    db_session,
    init_local_database,
)


PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent
WEB_DIR = PACKAGE_DIR / "web"
PUBLIC_DIR = ROOT

GOOGLE_CLIENT_ID = os.environ.get("MW_GOOGLE_CLIENT_ID", "").strip()
IS_PRODUCTION = (
    bool(os.environ.get("VERCEL")) or os.environ.get("MW_ENV") == "production"
)
SESSION_SECRET = os.environ.get("MW_SESSION_SECRET", "").strip()
if IS_PRODUCTION and len(SESSION_SECRET) < 48:
    raise RuntimeError(
        "MW_SESSION_SECRET must be set to at least 48 characters in production"
    )
SESSION_SECRET = SESSION_SECRET or secrets.token_urlsafe(48)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
INTERVIEW_MODEL = os.environ.get("MW_INTERVIEW_MODEL", "gpt-4o-mini").strip()
TRANSCRIBE_MODEL = os.environ.get(
    "MW_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"
).strip()
DEV_AUTH = os.environ.get("MW_DEV_AUTH", "").strip() == "1"
LOCAL_DEV_AUTH = DEV_AUTH and not IS_PRODUCTION
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "MW_ALLOWED_HOSTS",
        "*.vercel.app" if IS_PRODUCTION else "127.0.0.1,localhost,testserver",
    ).split(",")
    if host.strip()
]
INVITE_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 3 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
}

INTERVIEWER_INSTRUCTIONS = """
You are Memory Weaver, an attentive oral-history companion helping someone preserve one true personal or family memory through a relaxed conversation.

Conversation rules:
- Write like a thoughtful person in a real chat, not a questionnaire, therapist, customer-support agent, or motivational coach.
- Keep each reply to one or two sentences and no more than 45 words.
- Ask exactly one question per reply. Make it easy to answer.
- Ground every follow-up in a specific person, object, phrase, place, action, or feeling from the person's latest answer.
- Acknowledge a detail only when it adds meaning. Do not praise the person or pad the reply with enthusiasm.
- Never use generic phrases such as "I'm looking forward to hearing your stories", "thank you for sharing", "that sounds wonderful", "I'd love to hear more", or "meaningful or significant".
- Match the person's language and level of formality. If they mix languages, follow their style naturally.
- Never invent facts, names, emotions, dates, or motivations. Gently clarify uncertainty instead.
- Move through the memory naturally: first establish the scene, then people and sensory detail, then what happened, then why it stayed with them. Do not force every stage.
- Do not repeat a question or ask for information already given. Prefer concrete questions over broad reflection.
- Respect boundaries immediately. If the person declines a topic, move on without pressure.
- Once the scene, people, sequence, and meaning are clear, say briefly that there is enough to shape the memory and ask whether anything important is missing.
- Do not summarize the whole interview unless the person asks. Do not produce a title or final story during the interview.

Return only your conversational reply, with no labels or markdown headings.
""".strip()


def detect_image_mime(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_story_image(upload: UploadFile, content: bytes) -> tuple[str, str]:
    if not content:
        raise HTTPException(status_code=400, detail="Choose an image to upload.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Images must be smaller than 3 MB.")

    detected_type = detect_image_mime(content)
    if not detected_type:
        raise HTTPException(
            status_code=415, detail="Choose a JPEG, PNG, or WebP image."
        )
    reported_type = (upload.content_type or "").lower().split(";", 1)[0].strip()
    if reported_type == "image/jpg":
        reported_type = "image/jpeg"
    if reported_type not in {"", "application/octet-stream", detected_type}:
        raise HTTPException(
            status_code=415, detail="The image format does not match the file."
        )

    unsafe_name = (upload.filename or "story-image").replace("\\", "/")
    original_name = Path(unsafe_name).name.replace("\x00", "")[:255]
    return detected_type, original_name or "story-image"


def accessible_story_owner_ids(session: Session, user_id: int) -> list[int]:
    return [
        user_id,
        *session.scalars(
            select(FamilyLink.relative_user_id).where(FamilyLink.user_id == user_id)
        ),
    ]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_template(
    path: Path, *, raw_vars: set[str] | None = None, **vars: str
) -> str:
    html = read_text(path)
    raw_vars = raw_vars or set()
    for k, v in vars.items():
        replacement = str(v) if k in raw_vars else html_lib.escape(str(v), quote=True)
        html = html.replace("{{" + k + "}}", replacement)
    return html


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return str(token)


def verify_csrf(request: Request) -> None:
    expected = str(request.session.get("csrf") or "")
    received = request.headers.get("x-csrf-token", "")
    if not expected or not received or not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def enforce_rate_limit(
    user_id: int, action: str, limit: int, window_seconds: int
) -> None:
    now = int(time.time())
    cutoff = now - window_seconds
    with db_session() as session:
        session.execute(
            delete(RateLimitEvent).where(RateLimitEvent.created_at < now - 86400)
        )
        count = session.scalar(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.user_id == user_id,
                RateLimitEvent.action == action,
                RateLimitEvent.created_at >= cutoff,
            )
        )
        if int(count or 0) >= limit:
            raise HTTPException(
                status_code=429, detail="Rate limit reached. Please try again later."
            )
        session.add(RateLimitEvent(user_id=user_id, action=action, created_at=now))


def user_from_session(request: Request) -> dict[str, Any] | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    with db_session() as session:
        user = session.get(User, int(uid))
        if not user:
            return None
        return user_dict(user)


def user_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
    }


def require_user(request: Request) -> dict[str, Any]:
    user = user_from_session(request)
    if not user:
        raise HTTPException(
            status_code=401, detail="Your session has ended. Please sign in again."
        )
    return user


class GoogleAuthIn(BaseModel):
    credential: str = Field(min_length=10, max_length=4096)


class StoryIn(BaseModel):
    kind: Literal["memory", "timeline_event"] = "memory"
    title: str = Field(min_length=1, max_length=140)
    content: str = Field(min_length=1, max_length=6000)
    tags: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1000, le=2100)

    @field_validator("title", "content")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        clean: list[str] = []
        for tag in tags:
            normalized = tag.strip()[:40]
            if normalized and normalized.lower() not in {
                item.lower() for item in clean
            }:
                clean.append(normalized)
        return clean[:12]


class InterviewStartIn(BaseModel):
    topic: str = Field(default="", max_length=500)


class InterviewMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


def get_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Guided storytelling is temporarily unavailable. Please try again later.",
        )
    return OpenAI(api_key=OPENAI_API_KEY)


app = FastAPI(
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="memory_weaver_session",
    same_site="lax",
    https_only=IS_PRODUCTION,
    max_age=30 * 24 * 60 * 60,
)


@app.on_event("startup")
def _startup() -> None:
    init_local_database()


@app.middleware("http")
async def same_origin_posts(request: Request, call_next):
    request.state.csp_nonce = secrets.token_urlsafe(18)
    if request.method in {
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    } and request.url.path.startswith("/api/"):
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(
                {"detail": "Cross-site request rejected"}, status_code=403
            )
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse(
                {"detail": "Cross-origin request rejected"}, status_code=403
            )
    response = await call_next(request)
    if request.url.path in {"/", "/login", "/app"}:
        response.headers["Cache-Control"] = "no-store"
    nonce = request.state.csp_nonce
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://accounts.google.com/gsi/client; "
        "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style "
        "https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https://accounts.google.com/gsi/; "
        "frame-src https://accounts.google.com/gsi/; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["Permissions-Policy"] = (
        "camera=(), geolocation=(), microphone=(self)"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(
        PUBLIC_DIR / "manifest.webmanifest", media_type="application/manifest+json"
    )


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse, include_in_schema=False)
def landing(request: Request) -> str:
    nonce = request.state.csp_nonce
    page = read_text(PUBLIC_DIR / "index.html")
    if user_from_session(request):
        page = page.replace('href="/login">Sign in</a>', 'href="/app">Open archive</a>')
        page = page.replace(
            'href="/login" aria-label="Sign in to add a story"',
            'href="/app" aria-label="Open your archive to add a story"',
        )
    return page.replace("<script", f'<script nonce="{nonce}"')


@app.get("/login", response_class=HTMLResponse)
def login(request: Request) -> str:
    if user_from_session(request):
        return RedirectResponse(url="/app")
    if not GOOGLE_CLIENT_ID and not LOCAL_DEV_AUTH:
        return render_template(WEB_DIR / "missing_client_id.html")
    dev_block = (
        '<button type="button" class="btn ghost" id="devLoginBtn">Local test login</button>'
        if LOCAL_DEV_AUTH
        else ""
    )
    return render_template(
        WEB_DIR / "login.html",
        raw_vars={"DEV_LOGIN_BLOCK"},
        GOOGLE_CLIENT_ID=GOOGLE_CLIENT_ID,
        DEV_LOGIN_BLOCK=dev_block,
        CSRF_TOKEN=csrf_token(request),
        CSP_NONCE=request.state.csp_nonce,
    )


@app.get("/app", response_class=HTMLResponse)
def app_page(request: Request) -> str:
    user = user_from_session(request)
    if not user:
        return RedirectResponse(url="/login")
    return render_template(
        WEB_DIR / "app.html",
        USER_NAME=user.get("name") or "You",
        CSRF_TOKEN=csrf_token(request),
        CSP_NONCE=request.state.csp_nonce,
    )


@app.get("/invite", response_class=HTMLResponse)
def invite_page(request: Request) -> str:
    destination = "/app" if user_from_session(request) else "/login"
    return render_template(
        WEB_DIR / "invite.html",
        DESTINATION=destination,
        CSP_NONCE=request.state.csp_nonce,
    )


@app.post("/api/auth/google")
def auth_google(
    payload: GoogleAuthIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Sign-in is temporarily unavailable. Please try again later.",
        )
    try:
        info = google_id_token.verify_oauth2_token(
            payload.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except Exception:
        raise HTTPException(
            status_code=401, detail="Google sign-in could not be verified"
        )

    sub = str(info.get("sub") or "")
    if not sub:
        raise HTTPException(status_code=401, detail="We could not verify this account")
    if info.get("email") and not info.get("email_verified", False):
        raise HTTPException(status_code=401, detail="Please use a verified account")

    email = info.get("email")
    name = info.get("name") or info.get("given_name") or "User"
    picture = info.get("picture")

    now = int(time.time())
    with db_session() as session:
        user = session.scalar(select(User).where(User.google_sub == sub))
        if user:
            user.email = email
            user.name = name
            user.picture = picture
        else:
            user = User(
                google_sub=sub,
                email=email,
                name=name,
                picture=picture,
                created_at=now,
            )
            session.add(user)
        session.flush()
        result = user_dict(user)
    request.session.clear()
    request.session["uid"] = int(result["id"])
    csrf_token(request)
    return JSONResponse({"user": result})


@app.post("/api/logout")
def logout(request: Request, _: None = Depends(verify_csrf)) -> JSONResponse:
    request.session.clear()
    return JSONResponse({"status": "ok"})


@app.post("/api/dev-login")
def dev_login(request: Request, _: None = Depends(verify_csrf)) -> JSONResponse:
    """Local test login. It exists only when MW_DEV_AUTH=1."""
    if not DEV_AUTH or IS_PRODUCTION:
        raise HTTPException(status_code=404, detail="Not found")
    now = int(time.time())
    with db_session() as session:
        user = session.scalar(select(User).where(User.google_sub == "local-dev-user"))
        if user:
            user.name = "Local Tester"
        else:
            user = User(
                google_sub="local-dev-user",
                email="dev@local.test",
                name="Local Tester",
                picture="",
                created_at=now,
            )
            session.add(user)
        session.flush()
        result = user_dict(user)
    request.session.clear()
    request.session["uid"] = int(result["id"])
    csrf_token(request)
    return JSONResponse({"user": result})


@app.get("/api/me")
def me(request: Request) -> JSONResponse:
    user = user_from_session(request)
    if not user:
        raise HTTPException(
            status_code=401, detail="Your session has ended. Please sign in again."
        )
    return JSONResponse({"user": user})


@app.get("/api/dashboard")
def dashboard(request: Request) -> JSONResponse:
    user = require_user(request)
    uid = int(user["id"])
    with db_session() as session:
        family_ids = list(
            session.scalars(
                select(FamilyLink.relative_user_id).where(FamilyLink.user_id == uid)
            )
        )
        stories = list(
            session.scalars(select(Story).where(Story.user_id.in_([uid, *family_ids])))
        )
    return JSONResponse(
        {
            "counts": {
                "stories": len(stories),
                "family": len(family_ids),
                "timeline": sum(
                    1 for story in stories if story.kind == "timeline_event"
                ),
            }
        }
    )


@app.get("/api/stories")
def list_stories(request: Request, scope: str = "family") -> JSONResponse:
    user = require_user(request)
    uid = int(user["id"])

    with db_session() as session:
        ids = [uid] if scope == "me" else accessible_story_owner_ids(session, uid)
        rows = session.execute(
            select(Story, User, StoryImage.story_id)
            .join(User, User.id == Story.user_id)
            .outerjoin(StoryImage, StoryImage.story_id == Story.id)
            .where(Story.user_id.in_(ids))
            .order_by(Story.created_at.desc(), Story.id.desc())
        ).all()
        out = [
            {
                "id": story.id,
                "kind": story.kind,
                "title": story.title,
                "content": story.content,
                "tags": story.tags_json or [],
                "year": story.year,
                "created_at": story.created_at,
                "image_url": (
                    f"/api/stories/{story.id}/image" if image_story_id else None
                ),
                "author": {"name": author.name, "picture": author.picture},
            }
            for story, author, image_story_id in rows
        ]
    return JSONResponse({"stories": out})


@app.post("/api/stories")
def create_story(
    payload: StoryIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    user = require_user(request)
    now = int(time.time())
    with db_session() as session:
        story = Story(
            user_id=int(user["id"]),
            kind=payload.kind,
            title=payload.title,
            content=payload.content,
            tags_json=payload.tags,
            year=payload.year,
            created_at=now,
        )
        session.add(story)
        session.flush()
        story_id = story.id
    return JSONResponse({"status": "ok", "id": story_id})


@app.post("/api/stories/with-image")
async def create_story_with_image(
    request: Request,
    kind: str = Form("memory"),
    title: str = Form(...),
    content: str = Form(...),
    tags: str = Form(""),
    year: str = Form(""),
    image: UploadFile = File(...),
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    user = require_user(request)
    uid = int(user["id"])
    enforce_rate_limit(uid, "image_upload", 30, 3600)
    try:
        parsed_year = int(year) if year.strip() else None
    except ValueError:
        raise HTTPException(status_code=422, detail="Enter a valid year.")
    payload = StoryIn(
        kind=kind,
        title=title,
        content=content,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
        year=parsed_year,
    )
    image_content = await image.read(MAX_IMAGE_BYTES + 1)
    mime_type, original_name = validate_story_image(image, image_content)
    now = int(time.time())
    with db_session() as session:
        story = Story(
            user_id=uid,
            kind=payload.kind,
            title=payload.title,
            content=payload.content,
            tags_json=payload.tags,
            year=payload.year,
            created_at=now,
        )
        session.add(story)
        session.flush()
        session.add(
            StoryImage(
                story_id=story.id,
                mime_type=mime_type,
                original_name=original_name,
                image_data=image_content,
                byte_size=len(image_content),
                created_at=now,
            )
        )
        story_id = story.id
    return JSONResponse(
        {
            "status": "ok",
            "id": story_id,
            "image_url": f"/api/stories/{story_id}/image",
        }
    )


@app.post("/api/stories/{story_id}/image")
async def upload_story_image(
    story_id: int,
    request: Request,
    image: UploadFile = File(...),
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    user = require_user(request)
    uid = int(user["id"])
    enforce_rate_limit(uid, "image_upload", 30, 3600)
    content = await image.read(MAX_IMAGE_BYTES + 1)
    detected_type, original_name = validate_story_image(image, content)
    now = int(time.time())
    with db_session() as session:
        story = session.scalar(
            select(Story).where(Story.id == story_id, Story.user_id == uid)
        )
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")
        stored = session.get(StoryImage, story_id)
        if stored:
            stored.mime_type = detected_type
            stored.original_name = original_name
            stored.image_data = content
            stored.byte_size = len(content)
            stored.created_at = now
        else:
            session.add(
                StoryImage(
                    story_id=story_id,
                    mime_type=detected_type,
                    original_name=original_name,
                    image_data=content,
                    byte_size=len(content),
                    created_at=now,
                )
            )
    return JSONResponse({"status": "ok", "image_url": f"/api/stories/{story_id}/image"})


@app.get("/api/stories/{story_id}/image")
def get_story_image(story_id: int, request: Request) -> Response:
    user = require_user(request)
    uid = int(user["id"])
    with db_session() as session:
        owner_ids = accessible_story_owner_ids(session, uid)
        stored = session.scalar(
            select(StoryImage)
            .join(Story, Story.id == StoryImage.story_id)
            .where(StoryImage.story_id == story_id, Story.user_id.in_(owner_ids))
        )
        if not stored:
            raise HTTPException(status_code=404, detail="Image not found")
        image_data = stored.image_data
        mime_type = stored.mime_type
    return Response(
        content=image_data,
        media_type=mime_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.post("/api/transcribe")
async def transcribe_audio(
    request: Request,
    audio: UploadFile = File(...),
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    user = require_user(request)
    enforce_rate_limit(int(user["id"]), "transcribe", 20, 3600)
    content_type = (audio.content_type or "").lower().split(";", 1)[0].strip()
    if content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=415, detail="This recording format is not supported."
        )
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="No audio was captured.")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413, detail="Audio recording is too large (maximum 4 MB)"
        )

    extension = (
        "m4a"
        if "mp4" in content_type or "m4a" in content_type
        else content_type.rsplit("/", 1)[-1]
    )
    filename = f"memory-recording.{extension}"
    try:
        result = get_openai_client().audio.transcriptions.create(
            model=TRANSCRIBE_MODEL,
            file=(filename, content, content_type),
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="We could not transcribe this recording. Please try again in a moment.",
        )

    text = getattr(result, "text", None) or str(result)
    return JSONResponse({"text": text.strip()})


def get_interview_for_user(
    session: Session, session_id: int, user_id: int
) -> InterviewSession:
    interview = session.scalar(
        select(InterviewSession).where(
            InterviewSession.id == session_id,
            InterviewSession.user_id == user_id,
        )
    )
    if not interview:
        raise HTTPException(
            status_code=404, detail="This interview is no longer available."
        )
    return interview


def interview_history(session: Session, session_id: int) -> list[dict[str, str]]:
    rows = list(
        session.scalars(
            select(InterviewMessage)
            .where(InterviewMessage.session_id == session_id)
            .order_by(InterviewMessage.id.desc())
            .limit(40)
        )
    )
    rows.reverse()
    return [{"role": row.role, "content": row.content} for row in rows]


@app.post("/api/interviews")
def start_interview(
    payload: InterviewStartIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    user = require_user(request)
    enforce_rate_limit(int(user["id"]), "interview_start", 10, 3600)
    topic = payload.topic.strip()
    now = int(time.time())
    start_prompt = (
        f'The person wants to talk about "{topic}". Begin immediately with one relaxed, concrete question that helps place them inside a specific moment. Do not greet them or express excitement.'
        if topic
        else "Begin immediately with one relaxed question that helps the person choose a specific moment to revisit. Do not greet them, praise them, or say you are looking forward to their stories."
    )
    try:
        response = get_openai_client().responses.create(
            model=INTERVIEW_MODEL,
            instructions=INTERVIEWER_INSTRUCTIONS,
            input=start_prompt,
            max_output_tokens=220,
        )
        reply = response.output_text.strip()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="The guided interview is unavailable right now. Please try again later.",
        )

    with db_session() as session:
        interview = InterviewSession(
            user_id=int(user["id"]),
            topic=topic,
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(interview)
        session.flush()
        session_id = interview.id
        session.add(
            InterviewMessage(
                session_id=session_id,
                role="assistant",
                content=reply,
                created_at=now,
            )
        )
    return JSONResponse({"interview_id": session_id, "reply": reply})


@app.post("/api/interviews/{session_id}/messages")
def continue_interview(
    session_id: int,
    payload: InterviewMessageIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    user = require_user(request)
    uid = int(user["id"])
    enforce_rate_limit(uid, "interview_message", 100, 3600)
    now = int(time.time())
    message = payload.message.strip()
    with db_session() as session:
        interview = get_interview_for_user(session, session_id, uid)
        if interview.status != "active":
            raise HTTPException(
                status_code=400, detail="This interview is already complete"
            )
        history = interview_history(session, session_id)
    history.append({"role": "user", "content": message})

    try:
        response = get_openai_client().responses.create(
            model=INTERVIEW_MODEL,
            instructions=INTERVIEWER_INSTRUCTIONS,
            input=history,
            max_output_tokens=260,
        )
        reply = response.output_text.strip()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="The interviewer could not respond just now. Your answer is still here; please try again.",
        )

    with db_session() as session:
        interview = get_interview_for_user(session, session_id, uid)
        if interview.status != "active":
            raise HTTPException(
                status_code=400, detail="This interview is already complete"
            )
        session.add_all(
            [
                InterviewMessage(
                    session_id=session_id,
                    role="user",
                    content=message,
                    created_at=now,
                ),
                InterviewMessage(
                    session_id=session_id,
                    role="assistant",
                    content=reply,
                    created_at=int(time.time()),
                ),
            ]
        )
        interview.updated_at = int(time.time())
    return JSONResponse({"reply": reply})


@app.post("/api/interviews/{session_id}/finalize")
def finalize_interview(
    session_id: int,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    user = require_user(request)
    uid = int(user["id"])
    enforce_rate_limit(uid, "interview_finalize", 10, 3600)
    with db_session() as session:
        interview = get_interview_for_user(session, session_id, uid)
        history = interview_history(session, session_id)
        topic = interview.topic
        if not any(message["role"] == "user" for message in history):
            raise HTTPException(
                status_code=400,
                detail="Answer at least one question before saving a story",
            )

    transcript = "\n\n".join(
        ("Interviewer" if m["role"] == "assistant" else "Storyteller")
        + ": "
        + m["content"]
        for m in history
    )
    finalize_prompt = f"""
Turn this oral-history interview into a faithful first-person memory. Preserve the storyteller's voice and language.
Do not invent details. Keep culturally specific words. Use 3-8 short paragraphs.

Return strict JSON only with this shape:
{{"title":"short evocative title","content":"polished first-person story","tags":["3","to","6","relevant","tags"],"year":null}}
Use an integer year only if the storyteller clearly stated one; otherwise use null.

Interview topic: {topic or "not specified"}

Transcript:
{transcript}
""".strip()
    try:
        response = get_openai_client().responses.create(
            model=INTERVIEW_MODEL,
            instructions="You are a careful oral-history editor. Accuracy and the storyteller's voice matter more than literary flourish.",
            input=finalize_prompt,
            max_output_tokens=1800,
        )
        raw = response.output_text.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Model did not return JSON")
        draft = json.loads(raw[start : end + 1])
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="We could not shape this interview into a story just now. Please try again later.",
        )

    title = str(draft.get("title") or topic or "A Family Memory").strip()[:140]
    content = str(draft.get("content") or "").strip()
    if not content:
        raise HTTPException(
            status_code=502,
            detail="We could not complete this story. Please try again.",
        )
    tags = [str(t).strip() for t in (draft.get("tags") or []) if str(t).strip()][:8]
    year = draft.get("year") if isinstance(draft.get("year"), int) else None
    now = int(time.time())
    with db_session() as session:
        interview = get_interview_for_user(session, session_id, uid)
        story = Story(
            user_id=uid,
            kind="memory",
            title=title,
            content=content,
            tags_json=tags,
            year=year,
            created_at=now,
        )
        session.add(story)
        interview.status = "complete"
        interview.updated_at = now
        session.flush()
        story_id = story.id
    return JSONResponse(
        {
            "story": {
                "id": story_id,
                "title": title,
                "content": content,
                "tags": tags,
                "year": year,
            }
        }
    )


@app.get("/api/family")
def list_family(request: Request) -> JSONResponse:
    user = require_user(request)
    with db_session() as session:
        relatives = session.scalars(
            select(User)
            .join(FamilyLink, FamilyLink.relative_user_id == User.id)
            .where(FamilyLink.user_id == int(user["id"]))
            .order_by(User.name.asc())
        ).all()
        family = [user_dict(relative) for relative in relatives]
    return JSONResponse({"family": family})


@app.post("/api/family/invite")
def create_invite(request: Request, _: None = Depends(verify_csrf)) -> JSONResponse:
    user = require_user(request)
    token = secrets.token_urlsafe(18)
    now = int(time.time())
    expires_at = now + INVITE_TTL_SECONDS
    with db_session() as session:
        session.add(
            Invite(
                token=hash_invite_token(token),
                from_user_id=int(user["id"]),
                created_at=now,
                expires_at=expires_at,
            )
        )
    return JSONResponse({"url": f"/invite#{token}", "expires_at": expires_at})


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=20, max_length=255)


@app.post("/api/family/accept")
def accept_invite(
    payload: AcceptInviteIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    user = require_user(request)
    uid = int(user["id"])
    now = int(time.time())
    with db_session() as session:
        invite = session.scalar(
            select(Invite)
            .where(Invite.token == hash_invite_token(payload.token))
            .with_for_update()
        )
        if not invite:
            raise HTTPException(status_code=404, detail="This invitation is invalid.")
        if invite.accepted_by_user_id:
            raise HTTPException(
                status_code=400, detail="This invitation has already been accepted."
            )
        if invite.expires_at < now:
            raise HTTPException(
                status_code=400,
                detail="This invitation has expired. Ask your relative for a new one.",
            )
        from_uid = int(invite.from_user_id)
        if from_uid == uid:
            raise HTTPException(
                status_code=400, detail="You cannot accept your own invitation."
            )

        invite.accepted_by_user_id = uid
        invite.accepted_at = now
        for left, right in ((from_uid, uid), (uid, from_uid)):
            existing = session.scalar(
                select(FamilyLink).where(
                    FamilyLink.user_id == left,
                    FamilyLink.relative_user_id == right,
                )
            )
            if not existing:
                session.add(
                    FamilyLink(user_id=left, relative_user_id=right, created_at=now)
                )
    return JSONResponse({"status": "ok"})


@app.get("/health")
def health() -> JSONResponse:
    try:
        with db_session() as session:
            session.execute(select(1))
    except Exception:
        return JSONResponse(
            {"status": "degraded", "database": "unavailable"}, status_code=503
        )
    return JSONResponse({"status": "ok", "database": "connected"})

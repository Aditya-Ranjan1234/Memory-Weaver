from __future__ import annotations

import hmac
import html
import io
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from memory_weaver.database import (
    Album,
    AlbumItem,
    Draft,
    FamilyLink,
    InterviewMessage,
    InterviewParticipant,
    InterviewSession,
    MediaAsset,
    MemoryCapsule,
    Notification,
    Person,
    Story,
    StoryComment,
    StoryImage,
    StoryPerson,
    StoryReaction,
    StoryRevision,
    StoryTranslation,
    User,
    db_session,
)


router = APIRouter(prefix="/api/archive", tags=["archive"])
EDIT_ROLES = {"owner", "editor"}
VALID_ROLES = {"editor", "contributor", "viewer"}
VALID_REACTIONS = {"heart", "smile", "applause", "remember"}
MAX_MEDIA_BYTES = 4 * 1024 * 1024
IMAGE_SIGNATURES = {
    "image/png": lambda value: value.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda value: value.startswith(b"\xff\xd8\xff"),
    "image/webp": lambda value: (
        len(value) >= 12 and value[:4] == b"RIFF" and value[8:12] == b"WEBP"
    ),
}
ALLOWED_AUDIO = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/m4a",
    "audio/webm",
    "audio/ogg",
}


def verify_csrf(request: Request) -> None:
    expected = str(request.session.get("csrf") or "")
    received = request.headers.get("x-csrf-token", "")
    if not expected or not received or not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def current_uid(request: Request) -> int:
    uid = request.session.get("uid")
    if not uid:
        raise HTTPException(
            status_code=401, detail="Your session has ended. Please sign in again."
        )
    return int(uid)


def connected_ids(session: Session, uid: int) -> list[int]:
    return [
        uid,
        *session.scalars(
            select(FamilyLink.relative_user_id).where(FamilyLink.user_id == uid)
        ),
    ]


def family_role(session: Session, owner_id: int, actor_id: int) -> str | None:
    if owner_id == actor_id:
        return "owner"
    return session.scalar(
        select(FamilyLink.role).where(
            FamilyLink.user_id == owner_id,
            FamilyLink.relative_user_id == actor_id,
        )
    )


def story_for_user(
    session: Session,
    story_id: int,
    uid: int,
    *,
    include_deleted: bool = False,
    edit: bool = False,
) -> Story:
    story = session.get(Story, story_id)
    role = family_role(session, story.user_id, uid) if story else None
    if (
        not story
        or (story.deleted_at and not include_deleted)
        or role is None
        or (edit and role not in EDIT_ROLES)
    ):
        raise HTTPException(status_code=404, detail="Story not found")
    return story


def add_notification(
    session: Session,
    user_id: int,
    kind: str,
    message: str,
    link: str | None = None,
) -> None:
    session.add(
        Notification(
            user_id=user_id,
            kind=kind,
            message=message[:500],
            link=link,
            created_at=int(time.time()),
        )
    )


def save_revision(session: Session, story: Story, editor_id: int) -> None:
    session.add(
        StoryRevision(
            story_id=story.id,
            editor_user_id=editor_id,
            title=story.title,
            content=story.content,
            tags_json=story.tags_json or [],
            year=story.year,
            location=story.location,
            language=story.language,
            created_at=int(time.time()),
        )
    )


class StoryUpdate(BaseModel):
    kind: Literal["memory", "timeline_event"] = "memory"
    title: str = Field(min_length=1, max_length=140)
    content: str = Field(min_length=1, max_length=12000)
    tags: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1000, le=2100)
    location: str | None = Field(default=None, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    language: str | None = Field(default=None, max_length=40)

    @field_validator("title", "content")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            clean = value.strip()[:40]
            if clean and clean.casefold() not in {item.casefold() for item in result}:
                result.append(clean)
        return result[:12]


class RoleUpdate(BaseModel):
    role: Literal["editor", "contributor", "viewer"]


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    relation: str | None = Field(default=None, max_length=80)
    parent_id: int | None = None
    linked_user_id: int | None = None
    birth_year: int | None = Field(default=None, ge=1000, le=2100)
    death_year: int | None = Field(default=None, ge=1000, le=2100)
    bio: str | None = Field(default=None, max_length=3000)


class CommentIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ReactionIn(BaseModel):
    emoji: Literal["heart", "smile", "applause", "remember"]


class CapsuleIn(BaseModel):
    title: str = Field(min_length=1, max_length=140)
    content: str = Field(min_length=1, max_length=12000)
    recipient_user_id: int | None = None
    unlock_at: int


class DraftIn(BaseModel):
    payload: dict[str, object]


class AlbumIn(BaseModel):
    title: str = Field(min_length=1, max_length=140)
    description: str | None = Field(default=None, max_length=3000)


class AlbumItemIn(BaseModel):
    media_id: int


class TranslationIn(BaseModel):
    language: str = Field(min_length=2, max_length=40)


class ParticipantIn(BaseModel):
    user_id: int


@router.patch("/stories/{story_id}")
def update_story(
    story_id: int,
    payload: StoryUpdate,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    now = int(time.time())
    with db_session() as session:
        story = story_for_user(session, story_id, uid, edit=True)
        save_revision(session, story, uid)
        for key in (
            "kind",
            "title",
            "content",
            "year",
            "location",
            "latitude",
            "longitude",
            "language",
        ):
            setattr(story, key, getattr(payload, key))
        story.tags_json = payload.tags
        story.updated_at = now
        if story.user_id != uid:
            add_notification(
                session,
                story.user_id,
                "story_edited",
                "A family editor updated your story.",
                f"#story-{story.id}",
            )
    return JSONResponse({"status": "ok", "id": story_id})


@router.delete("/stories/{story_id}")
def delete_story(
    story_id: int,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        story = story_for_user(session, story_id, uid, edit=True)
        save_revision(session, story, uid)
        story.deleted_at = int(time.time())
        story.updated_at = story.deleted_at
    return JSONResponse({"status": "ok"})


@router.get("/stories/deleted")
def deleted_stories(request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        rows = session.scalars(
            select(Story)
            .where(Story.user_id == uid, Story.deleted_at.is_not(None))
            .order_by(Story.deleted_at.desc())
        ).all()
        result = [
            {"id": row.id, "title": row.title, "deleted_at": row.deleted_at}
            for row in rows
        ]
    return JSONResponse({"stories": result})


@router.post("/stories/{story_id}/restore")
def restore_deleted_story(
    story_id: int,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        story = story_for_user(session, story_id, uid, include_deleted=True, edit=True)
        story.deleted_at = None
        story.updated_at = int(time.time())
    return JSONResponse({"status": "ok"})


@router.get("/stories/{story_id}/revisions")
def story_revisions(story_id: int, request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        story_for_user(session, story_id, uid, include_deleted=True)
        rows = session.scalars(
            select(StoryRevision)
            .where(StoryRevision.story_id == story_id)
            .order_by(StoryRevision.id.desc())
        ).all()
        result = [
            {
                "id": row.id,
                "title": row.title,
                "content": row.content,
                "tags": row.tags_json or [],
                "year": row.year,
                "location": row.location,
                "language": row.language,
                "created_at": row.created_at,
                "editor_user_id": row.editor_user_id,
            }
            for row in rows
        ]
    return JSONResponse({"revisions": result})


@router.post("/stories/{story_id}/revisions/{revision_id}/restore")
def restore_revision(
    story_id: int,
    revision_id: int,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        story = story_for_user(session, story_id, uid, include_deleted=True, edit=True)
        revision = session.scalar(
            select(StoryRevision).where(
                StoryRevision.id == revision_id,
                StoryRevision.story_id == story_id,
            )
        )
        if not revision:
            raise HTTPException(status_code=404, detail="Revision not found")
        save_revision(session, story, uid)
        story.title = revision.title
        story.content = revision.content
        story.tags_json = revision.tags_json
        story.year = revision.year
        story.location = revision.location
        story.language = revision.language
        story.deleted_at = None
        story.updated_at = int(time.time())
    return JSONResponse({"status": "ok"})


@router.get("/search")
def advanced_search(
    request: Request,
    q: str = "",
    tag: str = "",
    person: str = "",
    location: str = "",
    year_from: int | None = None,
    year_to: int | None = None,
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        ids = connected_ids(session, uid)
        query = (
            select(Story, User)
            .join(User, User.id == Story.user_id)
            .where(Story.user_id.in_(ids), Story.deleted_at.is_(None))
        )
        if q.strip():
            term = f"%{q.strip()}%"
            query = query.where(
                or_(
                    Story.title.ilike(term),
                    Story.content.ilike(term),
                    Story.location.ilike(term),
                    User.name.ilike(term),
                )
            )
        if location.strip():
            query = query.where(Story.location.ilike(f"%{location.strip()}%"))
        if year_from is not None:
            query = query.where(Story.year >= year_from)
        if year_to is not None:
            query = query.where(Story.year <= year_to)
        rows = session.execute(query.order_by(Story.created_at.desc())).all()
        result = []
        for story, author in rows:
            tags = story.tags_json or []
            if tag and tag.casefold() not in {value.casefold() for value in tags}:
                continue
            if person:
                names = session.scalars(
                    select(Person.name)
                    .join(StoryPerson, StoryPerson.person_id == Person.id)
                    .where(StoryPerson.story_id == story.id)
                ).all()
                if not any(person.casefold() in name.casefold() for name in names):
                    continue
            result.append(
                {
                    "id": story.id,
                    "title": story.title,
                    "content": story.content,
                    "tags": tags,
                    "year": story.year,
                    "location": story.location,
                    "author": author.name,
                }
            )
    return JSONResponse({"stories": result})


@router.patch("/family/{relative_id}/role")
def update_family_role(
    relative_id: int,
    payload: RoleUpdate,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        link = session.scalar(
            select(FamilyLink).where(
                FamilyLink.user_id == uid,
                FamilyLink.relative_user_id == relative_id,
            )
        )
        if not link:
            raise HTTPException(status_code=404, detail="Family member not found")
        link.role = payload.role
        add_notification(
            session,
            relative_id,
            "role_changed",
            f"Your archive role was changed to {payload.role}.",
            "#family",
        )
    return JSONResponse({"status": "ok", "role": payload.role})


@router.get("/people")
def list_people(request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        ids = connected_ids(session, uid)
        rows = session.scalars(
            select(Person)
            .where(Person.owner_user_id.in_(ids))
            .order_by(Person.birth_year.asc(), Person.name.asc())
        ).all()
        result = [
            {
                "id": row.id,
                "owner_user_id": row.owner_user_id,
                "linked_user_id": row.linked_user_id,
                "parent_id": row.parent_id,
                "name": row.name,
                "relation": row.relation,
                "birth_year": row.birth_year,
                "death_year": row.death_year,
                "bio": row.bio,
            }
            for row in rows
        ]
    return JSONResponse({"people": result})


@router.post("/people")
def create_person(
    payload: PersonIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        ids = connected_ids(session, uid)
        if payload.linked_user_id is not None and payload.linked_user_id not in ids:
            raise HTTPException(status_code=422, detail="Choose a connected relative")
        if payload.parent_id is not None:
            parent = session.get(Person, payload.parent_id)
            if not parent or parent.owner_user_id not in ids:
                raise HTTPException(
                    status_code=422, detail="Choose a family-tree parent"
                )
        person = Person(
            owner_user_id=uid,
            created_at=int(time.time()),
            **payload.model_dump(),
        )
        session.add(person)
        session.flush()
        person_id = person.id
    return JSONResponse({"status": "ok", "id": person_id})


@router.delete("/people/{person_id}")
def delete_person(
    person_id: int,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        person = session.scalar(
            select(Person).where(Person.id == person_id, Person.owner_user_id == uid)
        )
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        session.delete(person)
    return JSONResponse({"status": "ok"})


@router.post("/stories/{story_id}/people/{person_id}")
def attach_person(
    story_id: int,
    person_id: int,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        story_for_user(session, story_id, uid, edit=True)
        person = session.get(Person, person_id)
        if not person or person.owner_user_id not in connected_ids(session, uid):
            raise HTTPException(status_code=404, detail="Person not found")
        existing = session.scalar(
            select(StoryPerson).where(
                StoryPerson.story_id == story_id, StoryPerson.person_id == person_id
            )
        )
        if not existing:
            session.add(StoryPerson(story_id=story_id, person_id=person_id))
    return JSONResponse({"status": "ok"})


def media_kind_and_type(upload: UploadFile, data: bytes) -> tuple[str, str]:
    reported = (upload.content_type or "").split(";", 1)[0].lower().strip()
    for mime, validator in IMAGE_SIGNATURES.items():
        if validator(data):
            if reported not in {"", "application/octet-stream", mime, "image/jpg"}:
                raise HTTPException(status_code=415, detail="Image type mismatch")
            return "image", mime
    if reported in ALLOWED_AUDIO:
        return "audio", reported
    raise HTTPException(
        status_code=415, detail="Choose a JPG, PNG, WebP, or audio file"
    )


@router.post("/stories/{story_id}/media")
async def upload_media(
    story_id: int,
    request: Request,
    file: UploadFile = File(...),
    caption: str = Form(""),
    location: str = Form(""),
    taken_at: str = Form(""),
    transcript: str = Form(""),
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    data = await file.read(MAX_MEDIA_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Choose a file")
    if len(data) > MAX_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail="Media must be smaller than 4 MB")
    kind, mime = media_kind_and_type(file, data)
    with db_session() as session:
        story = story_for_user(session, story_id, uid, edit=True)
        asset = MediaAsset(
            owner_user_id=story.user_id,
            story_id=story.id,
            kind=kind,
            mime_type=mime,
            original_name=Path(file.filename or "archive-media").name[:255],
            data=data,
            byte_size=len(data),
            caption=caption.strip()[:500] or None,
            location=location.strip()[:255] or None,
            taken_at=taken_at.strip()[:40] or None,
            transcript=transcript.strip()[:12000] or None,
            created_at=int(time.time()),
        )
        session.add(asset)
        session.flush()
        media_id = asset.id
    return JSONResponse(
        {
            "status": "ok",
            "id": media_id,
            "kind": kind,
            "url": f"/api/archive/media/{media_id}",
        }
    )


@router.get("/media/{media_id}")
def get_media(media_id: int, request: Request) -> Response:
    uid = current_uid(request)
    with db_session() as session:
        asset = session.get(MediaAsset, media_id)
        if not asset or asset.owner_user_id not in connected_ids(session, uid):
            raise HTTPException(status_code=404, detail="Media not found")
        data = asset.data
        mime = asset.mime_type
    return Response(
        data, media_type=mime, headers={"Cache-Control": "private, max-age=3600"}
    )


@router.delete("/media/{media_id}")
def delete_media(
    media_id: int,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        asset = session.get(MediaAsset, media_id)
        if not asset or asset.owner_user_id != uid:
            raise HTTPException(status_code=404, detail="Media not found")
        session.delete(asset)
    return JSONResponse({"status": "ok"})


@router.get("/albums")
def list_albums(request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        ids = connected_ids(session, uid)
        albums = session.scalars(
            select(Album).where(Album.owner_user_id.in_(ids)).order_by(Album.id.desc())
        ).all()
        result = []
        for album in albums:
            media = (
                session.execute(
                    select(MediaAsset)
                    .join(AlbumItem, AlbumItem.media_id == MediaAsset.id)
                    .where(AlbumItem.album_id == album.id)
                    .order_by(AlbumItem.position, AlbumItem.id)
                )
                .scalars()
                .all()
            )
            result.append(
                {
                    "id": album.id,
                    "title": album.title,
                    "description": album.description,
                    "owner_user_id": album.owner_user_id,
                    "media": [
                        {
                            "id": item.id,
                            "kind": item.kind,
                            "caption": item.caption,
                            "url": f"/api/archive/media/{item.id}",
                        }
                        for item in media
                    ],
                }
            )
    return JSONResponse({"albums": result})


@router.post("/albums")
def create_album(
    payload: AlbumIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        album = Album(
            owner_user_id=uid,
            title=payload.title.strip(),
            description=(payload.description or "").strip() or None,
            created_at=int(time.time()),
        )
        session.add(album)
        session.flush()
        album_id = album.id
    return JSONResponse({"status": "ok", "id": album_id})


@router.post("/albums/{album_id}/items")
def add_album_item(
    album_id: int,
    payload: AlbumItemIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        album = session.scalar(
            select(Album).where(Album.id == album_id, Album.owner_user_id == uid)
        )
        media = session.scalar(
            select(MediaAsset).where(
                MediaAsset.id == payload.media_id, MediaAsset.owner_user_id == uid
            )
        )
        if not album or not media:
            raise HTTPException(status_code=404, detail="Album or media not found")
        existing = session.scalar(
            select(AlbumItem).where(
                AlbumItem.album_id == album_id,
                AlbumItem.media_id == payload.media_id,
            )
        )
        if not existing:
            position = int(
                session.scalar(
                    select(func.count())
                    .select_from(AlbumItem)
                    .where(AlbumItem.album_id == album_id)
                )
                or 0
            )
            session.add(
                AlbumItem(
                    album_id=album_id, media_id=payload.media_id, position=position
                )
            )
    return JSONResponse({"status": "ok"})


@router.get("/capsules")
def list_capsules(request: Request) -> JSONResponse:
    uid = current_uid(request)
    now = int(time.time())
    with db_session() as session:
        rows = session.scalars(
            select(MemoryCapsule)
            .where(
                or_(
                    MemoryCapsule.owner_user_id == uid,
                    MemoryCapsule.recipient_user_id == uid,
                )
            )
            .order_by(MemoryCapsule.unlock_at.asc())
        ).all()
        result = []
        for row in rows:
            unlocked = row.owner_user_id == uid or row.unlock_at <= now
            result.append(
                {
                    "id": row.id,
                    "title": row.title,
                    "content": row.content if unlocked else None,
                    "unlock_at": row.unlock_at,
                    "unlocked": unlocked,
                    "recipient_user_id": row.recipient_user_id,
                    "owner_user_id": row.owner_user_id,
                }
            )
    return JSONResponse({"capsules": result})


@router.post("/capsules")
def create_capsule(
    payload: CapsuleIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        if payload.recipient_user_id not in {None, *connected_ids(session, uid)}:
            raise HTTPException(status_code=422, detail="Choose a connected relative")
        capsule = MemoryCapsule(
            owner_user_id=uid,
            recipient_user_id=payload.recipient_user_id,
            title=payload.title.strip(),
            content=payload.content.strip(),
            unlock_at=payload.unlock_at,
            created_at=int(time.time()),
        )
        session.add(capsule)
        session.flush()
        capsule_id = capsule.id
        if payload.recipient_user_id:
            add_notification(
                session,
                payload.recipient_user_id,
                "capsule",
                "A memory capsule is waiting for you.",
                "#capsules",
            )
    return JSONResponse({"status": "ok", "id": capsule_id})


@router.get("/stories/{story_id}/social")
def story_social(story_id: int, request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        story_for_user(session, story_id, uid)
        comments = session.execute(
            select(StoryComment, User)
            .join(User, User.id == StoryComment.user_id)
            .where(StoryComment.story_id == story_id)
            .order_by(StoryComment.id.asc())
        ).all()
        reactions = session.execute(
            select(StoryReaction.emoji, func.count())
            .where(StoryReaction.story_id == story_id)
            .group_by(StoryReaction.emoji)
        ).all()
        mine = session.scalar(
            select(StoryReaction.emoji).where(
                StoryReaction.story_id == story_id, StoryReaction.user_id == uid
            )
        )
        result_comments = [
            {
                "id": comment.id,
                "content": comment.content,
                "created_at": comment.created_at,
                "author": user.name,
                "mine": comment.user_id == uid,
            }
            for comment, user in comments
        ]
    return JSONResponse(
        {
            "comments": result_comments,
            "reactions": {emoji: count for emoji, count in reactions},
            "mine": mine,
        }
    )


@router.post("/stories/{story_id}/comments")
def add_comment(
    story_id: int,
    payload: CommentIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        story = story_for_user(session, story_id, uid)
        comment = StoryComment(
            story_id=story.id,
            user_id=uid,
            content=payload.content.strip(),
            created_at=int(time.time()),
        )
        session.add(comment)
        if story.user_id != uid:
            add_notification(
                session,
                story.user_id,
                "comment",
                "A relative commented on your story.",
                f"#story-{story.id}",
            )
    return JSONResponse({"status": "ok"})


@router.put("/stories/{story_id}/reaction")
def react_to_story(
    story_id: int,
    payload: ReactionIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        story = story_for_user(session, story_id, uid)
        reaction = session.scalar(
            select(StoryReaction).where(
                StoryReaction.story_id == story_id, StoryReaction.user_id == uid
            )
        )
        if reaction:
            reaction.emoji = payload.emoji
        else:
            session.add(
                StoryReaction(
                    story_id=story_id,
                    user_id=uid,
                    emoji=payload.emoji,
                    created_at=int(time.time()),
                )
            )
        if story.user_id != uid:
            add_notification(
                session,
                story.user_id,
                "reaction",
                "A relative reacted to your story.",
                f"#story-{story.id}",
            )
    return JSONResponse({"status": "ok"})


@router.get("/notifications")
def list_notifications(request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        now = int(time.time())
        today = time.gmtime(now)
        day_start = now - 86400
        for story in session.scalars(
            select(Story).where(
                Story.user_id.in_(connected_ids(session, uid)),
                Story.deleted_at.is_(None),
                Story.created_at < now - 31536000,
            )
        ):
            created = time.gmtime(story.created_at)
            if (created.tm_mon, created.tm_mday) != (today.tm_mon, today.tm_mday):
                continue
            exists = session.scalar(
                select(Notification.id).where(
                    Notification.user_id == uid,
                    Notification.kind == "anniversary",
                    Notification.link == f"#story-{story.id}",
                    Notification.created_at >= day_start,
                )
            )
            if not exists:
                add_notification(
                    session,
                    uid,
                    "anniversary",
                    f'Remembering "{story.title}" today.',
                    f"#story-{story.id}",
                )
        rows = session.scalars(
            select(Notification)
            .where(Notification.user_id == uid)
            .order_by(Notification.id.desc())
            .limit(50)
        ).all()
        result = [
            {
                "id": row.id,
                "kind": row.kind,
                "message": row.message,
                "link": row.link,
                "read": row.read_at is not None,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    return JSONResponse({"notifications": result})


@router.post("/notifications/read")
def read_notifications(
    request: Request, _: None = Depends(verify_csrf)
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        for row in session.scalars(
            select(Notification).where(
                Notification.user_id == uid, Notification.read_at.is_(None)
            )
        ):
            row.read_at = int(time.time())
    return JSONResponse({"status": "ok"})


@router.get("/drafts/{key}")
def get_draft(key: str, request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        draft = session.scalar(
            select(Draft).where(Draft.user_id == uid, Draft.key == key[:80])
        )
        payload = draft.payload_json if draft else None
    return JSONResponse({"payload": payload})


@router.put("/drafts/{key}")
def save_draft(
    key: str,
    payload: DraftIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    encoded = json.dumps(payload.payload)
    if len(encoded) > 30000:
        raise HTTPException(status_code=413, detail="Draft is too large")
    with db_session() as session:
        draft = session.scalar(
            select(Draft).where(Draft.user_id == uid, Draft.key == key[:80])
        )
        if draft:
            draft.payload_json = payload.payload
            draft.updated_at = int(time.time())
        else:
            session.add(
                Draft(
                    user_id=uid,
                    key=key[:80],
                    payload_json=payload.payload,
                    updated_at=int(time.time()),
                )
            )
    return JSONResponse({"status": "ok"})


@router.delete("/drafts/{key}")
def delete_draft(
    key: str,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        session.execute(
            delete(Draft).where(Draft.user_id == uid, Draft.key == key[:80])
        )
    return JSONResponse({"status": "ok"})


@router.post("/stories/{story_id}/translate")
def translate_story(
    story_id: int,
    payload: TranslationIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503, detail="Translation is temporarily unavailable"
        )
    with db_session() as session:
        story = story_for_user(session, story_id, uid)
        title, content = story.title, story.content
    prompt = (
        f"Translate this family memory into {payload.language}. Preserve names, cultural words, "
        "paragraphs, and meaning. Do not add details. Return strict JSON with title and content.\n\n"
        f"Title: {title}\n\n{content}"
    )
    try:
        response = OpenAI(api_key=api_key).responses.create(
            model=os.environ.get("MW_INTERVIEW_MODEL", "gpt-4o-mini"),
            input=prompt,
            max_output_tokens=1800,
        )
        raw = response.output_text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        translated = json.loads(raw)
        translated_title = str(translated["title"]).strip()[:140]
        translated_content = str(translated["content"]).strip()[:12000]
    except Exception:
        raise HTTPException(
            status_code=502, detail="Translation could not be completed"
        )
    with db_session() as session:
        existing = session.scalar(
            select(StoryTranslation).where(
                StoryTranslation.story_id == story_id,
                StoryTranslation.language == payload.language,
            )
        )
        if existing:
            existing.title = translated_title
            existing.content = translated_content
            existing.created_at = int(time.time())
        else:
            session.add(
                StoryTranslation(
                    story_id=story_id,
                    language=payload.language,
                    title=translated_title,
                    content=translated_content,
                    created_at=int(time.time()),
                )
            )
    return JSONResponse(
        {
            "language": payload.language,
            "title": translated_title,
            "content": translated_content,
        }
    )


@router.get("/stories/{story_id}/translations")
def list_translations(story_id: int, request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        story_for_user(session, story_id, uid)
        rows = session.scalars(
            select(StoryTranslation).where(StoryTranslation.story_id == story_id)
        ).all()
        result = [
            {"language": row.language, "title": row.title, "content": row.content}
            for row in rows
        ]
    return JSONResponse({"translations": result})


@router.post("/interviews/{session_id}/participants")
def add_interview_participant(
    session_id: int,
    payload: ParticipantIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        interview = session.scalar(
            select(InterviewSession).where(
                InterviewSession.id == session_id, InterviewSession.user_id == uid
            )
        )
        if not interview or payload.user_id not in connected_ids(session, uid):
            raise HTTPException(
                status_code=404, detail="Interview or relative not found"
            )
        existing = session.scalar(
            select(InterviewParticipant).where(
                InterviewParticipant.session_id == session_id,
                InterviewParticipant.user_id == payload.user_id,
            )
        )
        if not existing:
            session.add(
                InterviewParticipant(
                    session_id=session_id,
                    user_id=payload.user_id,
                    role="participant",
                    created_at=int(time.time()),
                )
            )
            add_notification(
                session,
                payload.user_id,
                "interview",
                "You were invited to a family interview.",
                f"#interview-{session_id}",
            )
    return JSONResponse({"status": "ok"})


@router.get("/interviews")
def list_collaborative_interviews(request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        rows = session.scalars(
            select(InterviewSession)
            .outerjoin(
                InterviewParticipant,
                InterviewParticipant.session_id == InterviewSession.id,
            )
            .where(
                or_(
                    InterviewSession.user_id == uid,
                    InterviewParticipant.user_id == uid,
                )
            )
            .distinct()
            .order_by(InterviewSession.updated_at.desc())
            .limit(20)
        ).all()
        result = [
            {
                "id": row.id,
                "topic": row.topic,
                "status": row.status,
                "owner_user_id": row.user_id,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]
    return JSONResponse({"interviews": result})


@router.get("/interviews/{session_id}")
def collaborative_interview(session_id: int, request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        interview = session.get(InterviewSession, session_id)
        participant = session.scalar(
            select(InterviewParticipant.id).where(
                InterviewParticipant.session_id == session_id,
                InterviewParticipant.user_id == uid,
            )
        )
        if not interview or (interview.user_id != uid and not participant):
            raise HTTPException(status_code=404, detail="Interview not found")
        messages = session.scalars(
            select(InterviewMessage)
            .where(InterviewMessage.session_id == session_id)
            .order_by(InterviewMessage.id.asc())
        ).all()
    return JSONResponse(
        {
            "id": interview.id,
            "topic": interview.topic,
            "status": interview.status,
            "messages": [
                {"role": row.role, "content": row.content, "created_at": row.created_at}
                for row in messages
            ],
        }
    )


def export_payload(session: Session, uid: int) -> dict[str, object]:
    stories = session.scalars(select(Story).where(Story.user_id == uid)).all()
    people = session.scalars(select(Person).where(Person.owner_user_id == uid)).all()
    capsules = session.scalars(
        select(MemoryCapsule).where(MemoryCapsule.owner_user_id == uid)
    ).all()
    media = session.scalars(
        select(MediaAsset).where(MediaAsset.owner_user_id == uid)
    ).all()
    return {
        "exported_at": int(time.time()),
        "stories": [
            {
                "id": row.id,
                "kind": row.kind,
                "title": row.title,
                "content": row.content,
                "tags": row.tags_json or [],
                "year": row.year,
                "location": row.location,
                "language": row.language,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "deleted_at": row.deleted_at,
            }
            for row in stories
        ],
        "people": [
            {
                "id": row.id,
                "name": row.name,
                "relation": row.relation,
                "parent_id": row.parent_id,
                "birth_year": row.birth_year,
                "death_year": row.death_year,
                "bio": row.bio,
            }
            for row in people
        ],
        "capsules": [
            {
                "title": row.title,
                "content": row.content,
                "recipient_user_id": row.recipient_user_id,
                "unlock_at": row.unlock_at,
            }
            for row in capsules
        ],
        "media_manifest": [
            {
                "id": row.id,
                "story_id": row.story_id,
                "kind": row.kind,
                "mime_type": row.mime_type,
                "original_name": row.original_name,
                "caption": row.caption,
                "transcript": row.transcript,
            }
            for row in media
        ],
    }


@router.get("/account/export")
def export_account(request: Request) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        payload = export_payload(session, uid)
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": 'attachment; filename="memory-weaver-export.json"'
        },
    )


@router.get("/account/export.zip")
def export_account_archive(request: Request) -> Response:
    uid = current_uid(request)
    with db_session() as session:
        payload = export_payload(session, uid)
        media = session.scalars(
            select(MediaAsset).where(MediaAsset.owner_user_id == uid)
        ).all()
        legacy_images = session.execute(
            select(StoryImage, Story)
            .join(Story, Story.id == StoryImage.story_id)
            .where(Story.user_id == uid)
        ).all()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "memory-weaver-data.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
            for asset in media:
                safe_name = Path(asset.original_name).name or f"media-{asset.id}"
                archive.writestr(f"media/{asset.id}-{safe_name}", asset.data)
            for asset, story in legacy_images:
                safe_name = Path(asset.original_name).name or f"story-{story.id}-image"
                archive.writestr(
                    f"media/legacy-{story.id}-{safe_name}", asset.image_data
                )
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="memory-weaver-archive.zip"'
        },
    )


@router.get("/storybook.pdf")
def storybook_pdf(request: Request) -> Response:
    uid = current_uid(request)
    with db_session() as session:
        user = session.get(User, uid)
        stories = session.scalars(
            select(Story)
            .where(
                Story.user_id.in_(connected_ids(session, uid)),
                Story.deleted_at.is_(None),
            )
            .order_by(Story.year.asc().nullslast(), Story.created_at.asc())
        ).all()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=22 * mm,
        leftMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title="Memory Weaver Storybook",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MWTitle",
        parent=styles["Title"],
        textColor=HexColor("#6f452d"),
        fontSize=28,
        leading=34,
        spaceAfter=16,
    )
    story_title = ParagraphStyle(
        "MWStoryTitle", parent=styles["Heading1"], textColor=HexColor("#2f4d3b")
    )
    flow = [
        Paragraph("Memory Weaver", title_style),
        Paragraph(
            f"The family stories of {(user.name if user else 'our family')}",
            styles["Heading2"],
        ),
        Spacer(1, 12 * mm),
        Paragraph(
            "A private collection of moments, voices, places, and traditions.",
            styles["BodyText"],
        ),
        PageBreak(),
    ]
    for index, story in enumerate(stories):
        heading = f"{story.year} / {story.title}" if story.year else story.title
        safe_location = html.escape(story.location or "")
        safe_content = html.escape(story.content).replace("\n", "<br/>")
        flow.extend(
            [
                Paragraph(html.escape(heading), story_title),
                Paragraph(safe_location, styles["Italic"]),
                Spacer(1, 4 * mm),
                Paragraph(safe_content, styles["BodyText"]),
            ]
        )
        if index < len(stories) - 1:
            flow.append(PageBreak())
    doc.build(flow)
    return Response(
        buffer.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="memory-weaver-storybook.pdf"'
        },
    )


class DeleteAccountIn(BaseModel):
    confirmation: Literal["DELETE MY ARCHIVE"]


@router.delete("/account")
def delete_account(
    payload: DeleteAccountIn,
    request: Request,
    _: None = Depends(verify_csrf),
) -> JSONResponse:
    uid = current_uid(request)
    with db_session() as session:
        user = session.get(User, uid)
        if not user:
            raise HTTPException(status_code=404, detail="Account not found")
        session.delete(user)
    request.session.clear()
    return JSONResponse({"status": "deleted"})

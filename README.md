# Memory Weaver

Memory Weaver is a mobile-first web app for capturing, organizing, and preserving family memories, with a special focus on elder storytelling and future memory capsules.

## What This Project Does

Memory Weaver helps families:

- Capture stories as text, media links, Reddit imports, and WhatsApp-style forwards
- Organize memories into timelines, recipes, and future capsules
- Build a family archive that can later grow into a chat experience or story book
- Keep the UX simple enough for a grandchild to guide an elder through it

## Live Features In This MVP

- Responsive homepage dashboard
- Memory capture form with working submit flow
- Demo-data loading
- Dashboard refresh
- Export to JSON
- Reset to demo data
- Timeline section
- Memory library
- Recipe and capsule examples

## Data Model

Each saved item stores:

- `kind` - `memory`, `timeline_event`, `recipe`, `capsule`, or `person`
- `title`
- `content`
- `source`
- `created_at`
- `person`
- `language`
- `tags`
- `metadata`

Local storage lives in:

- [`D:\6th Sem\Build FOr Good\memory_weaver_data.json`](D:/6th%20Sem/Build%20For%20Good/memory_weaver_data.json)

## Core Routes

- `GET /` - Main UI
- `GET /health` - Server health check
- `GET /api/dashboard` - Dashboard data
- `GET /api/export` - Download full JSON export
- `POST /api/seed` - Reload demo collection
- `POST /api/reset` - Reset to the built-in demo collection
- `POST /api/ingest` - Save a new memory

## Capture Sources

- `text`
- `reddit`
- `whatsapp`
- `voice`
- `photo`
- `video`
- `instagram`
- `url`

## Running Locally

Use the existing `venv` and run the app:

```powershell
.venv\Scripts\Activate.ps1
python app.py
```

Then open:

- [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Virtual Environment

The project is designed to run inside the local virtual environment at:

- [`D:\6th Sem\Build FOr Good\.venv`](D:/6th%20Sem/Build%20For%20Good/.venv)

If you ever need to recreate it:

```powershell
C:\Users\OMEN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Suggested Next Build Steps

- Add SQLite persistence
- Add authentication and family roles
- Add file uploads for audio, photos, and videos
- Add AI summarization and story generation
- Add a real chat UI for "Talk to Grandma"
- Add PDF export for the family story book

## Notes On Reddit And Instagram

- Reddit ingestion uses public JSON endpoints for posts and comments when available.
- Instagram Reels are treated as public URL references in this MVP.
- Anything private, auth-protected, or anti-bot constrained should use official APIs or user-provided exports.

## GitHub Project Info

- Repo name: `memory-weaver`
- Tags: `memory-archive`, `family-history`, `storybook`, `timeline`, `capture`, `fastapi-alternative`, `offline-first`, `reddit-import`, `web-app`
- One-line description: `A mobile-first web app for capturing family memories, building timelines, and preserving stories for future generations.`

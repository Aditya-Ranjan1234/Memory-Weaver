# Memory Weaver

Memory Weaver is a mobile-first family archive for preserving personal stories, shared timelines, cultural details, and the voices behind them.

## Features

- Google-only authentication with backend ID-token verification
- Private story creation with tags, dates, places, map coordinates, people, and multilingual originals
- Story editing, soft deletion, revision history, and one-click restoration
- Browser voice recording and OpenAI speech-to-text
- A chat-style AI oral-history interviewer with contextual, one-question follow-ups
- AI-assisted story creation that preserves the storyteller's language and details
- Interview templates and collaborative family interview sessions
- Seven-day, one-time family invitation links
- Hashed invitation tokens that stay out of request logs
- Owner, editor, contributor, and viewer archive permissions
- Combined stories, graphical timelines, place maps, and interactive family trees
- Multi-photo galleries, albums, original audio preservation, captions, and transcripts
- Private future memory capsules with recipient and unlock-date controls
- Family-only comments, reactions, and activity notifications
- Advanced search across story text, names, tags, places, people, and years
- Autosaved cloud/local drafts and an offline story queue through the PWA
- Original-language preservation and optional AI translations
- Story reader mode, read-aloud, larger text, and high-contrast accessibility controls
- Complete ZIP export with original media, JSON export, and PDF storybooks
- Account deletion and archive ownership controls
- Five-story pagination and working tag filters
- Responsive desktop and mobile interface
- SQLite support for local development and Neon Postgres for production
- CSRF protection, secure cookies, security headers, strict validation, and persistent AI rate limits

## Architecture

- `app.py`: local and Vercel FastAPI entry point
- `memory_weaver/app.py`: routes, authentication, OpenAI workflows, and page serving
- `memory_weaver/archive_api.py`: collaborative archive, media, privacy, export, and revision APIs
- `memory_weaver/database.py`: shared SQLAlchemy models and database sessions
- `memory_weaver/web/`: authenticated application, login, and invitation pages
- `index.html`, `favicon.svg`, `manifest.webmanifest`, `sw.js`: Vercel-visible landing page and PWA assets
- `migrations/`: Alembic production schema migrations
- `tests/`: isolated security and functionality tests
- `tools/story_seed/`: non-production demo seed utilities
- `docs/`: deployment and operational documentation
- `vercel.json`: Vercel Function configuration

## Local Setup

Always run the project inside its virtual environment.

```powershell
cd "D:\6th Sem\Build FOr Good"
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create `.env.local` from `.env.example`. This file is ignored by Git and Vercel.

```text
DATABASE_URL=sqlite:///./mw_local.db
DATABASE_URL_UNPOOLED=
MW_GOOGLE_CLIENT_ID=
MW_SESSION_SECRET=replace-with-a-long-random-value
OPENAI_API_KEY=
MW_INTERVIEW_MODEL=gpt-4o-mini
MW_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
MW_DEV_AUTH=1
MW_ALLOWED_HOSTS=127.0.0.1,localhost
```

Generate a session secret from the venv:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Run the app:

```powershell
python app.py
```

Open [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login). `MW_DEV_AUTH=1` enables the local test-login button and is forcibly disabled on Vercel.

## Google Authentication

Create a Google Identity Services Web application client and add these Authorized JavaScript origins:

```text
http://127.0.0.1:8000
http://localhost:8000
https://your-production-domain.example
```

Set the resulting client ID as `MW_GOOGLE_CLIENT_ID`. This sign-in flow needs the Web client ID, not the downloaded OAuth client JSON file or client secret.

## Neon Postgres

Connect a Neon database through the Vercel Marketplace. Use the pooled URL at runtime and the direct URL for migrations:

```text
DATABASE_URL=postgresql://...-pooler.../neondb?sslmode=require
DATABASE_URL_UNPOOLED=postgresql://.../neondb?sslmode=require
```

Apply migrations from the venv before the first production deployment:

```powershell
python -m alembic upgrade head
python -m alembic current
```

Never commit a database URL, password, API key, `.env.local`, or SQLite database.

## OpenAI

The server uses:

- `gpt-4o-mini` for interview questions and final story editing
- `gpt-4o-mini-transcribe` for voice-to-text

Store `OPENAI_API_KEY` only in the server environment. Voice recordings are currently transcribed and discarded rather than permanently stored.

The browser stops recordings at five minutes or about 3.8 MB so requests remain below Vercel's Function payload limit.

## Story Photos

Each story can include multiple private JPEG, PNG, or WebP images and original audio recordings. Media is validated, stored in Postgres, and served only to the story owner and accepted family connections. It does not receive public object-storage URLs. A complete account export includes the original files.

## Vercel Deployment

Follow the [secure deployment guide](docs/DEPLOYMENT.md). Production and Preview deployments must not share the same family-story database.

## Tests

Run all tests through the venv:

```powershell
python -m unittest discover -s tests -v
python -m alembic check
python -m pip_audit -r requirements.txt
ruff check app.py memory_weaver migrations tests
ruff format --check app.py memory_weaver migrations tests
$files = git ls-files -- . ':(exclude).secrets.baseline'
detect-secrets-hook --baseline .secrets.baseline $files
```

The test suite uses a temporary SQLite database and a mocked OpenAI client, so it does not spend API credits or modify production data.

## Privacy Notes

Family stories and voice recordings can contain sensitive personal data. Before a broad public launch, add reviewed privacy and terms pages and a clear disclosure that recordings, transcripts, interviews, and translations may be processed by OpenAI. Account export and deletion are available in the authenticated Settings screen. See [docs/SECURITY.md](docs/SECURITY.md) for reporting and credential-handling rules.

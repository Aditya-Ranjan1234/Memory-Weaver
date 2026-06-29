# Memory Weaver

Memory Weaver is a mobile-first memory archive that helps families preserve the voice, stories, recipes, and timelines of their elders before those details fade away.

## Pitch

Every family has stories that live in people, not documents.
Memory Weaver turns those stories into a living archive that can be captured in minutes, organized automatically, and replayed as a family memory book, timeline, or future message capsule.

## Why It Matters

- Families lose irreplaceable stories when elders pass before their memories are recorded
- Most tools are built for notes, not for voice, emotion, and cultural context
- Memory Weaver is designed for low-friction family capture, especially when a grandchild is helping an elder use it

## What It Does

- Captures family stories from text, media links, Reddit imports, and WhatsApp-style forwards
- Organizes memories into timelines, recipes, capsules, and story collections
- Preserves culturally specific details like dialect, place names, food, and family roles
- Keeps the experience simple enough to use on a phone during a 30-minute family conversation

## Live Features

- Responsive landing page and dashboard
- Memory capture form with working save flow
- Sample memory seed collection
- Timeline view
- Memory library
- Story tools panel
- Reset to demo data
- JSON export for portability

## Example Memory Types

- Childhood home descriptions
- Migration and city move stories
- First job stories
- Marriage memories
- Family recipes
- Festival songs
- Village market scenes
- Future memory capsules for weddings or milestones

## Data Model

Each memory stores:

- `kind`
- `title`
- `content`
- `source`
- `created_at`
- `person`
- `language`
- `tags`
- `metadata`

## Deployment

This repo is currently Vercel-ready as a static web app.

Best deployment targets:

- Vercel
- GitHub Pages
- Netlify

## Running Locally

Use the existing `venv` and open the app locally:

```powershell
.venv\Scripts\Activate.ps1
python app.py
```

Then open:

- [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Project Structure

- [`index.html`](index.html) - Static deployed web app
- [`app.py`](app.py) - Legacy local prototype logic
- [`vercel.json`](vercel.json) - Vercel config
- [`.gitignore`](.gitignore) - Ignore rules

## Virtual Environment

If you ever need to recreate the local `venv`:

```powershell
C:\Users\OMEN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Suggested Next Steps

- Add real uploads for audio, photos, and video
- Add family accounts and permissions
- Add timeline editing
- Add PDF book generation
- Add AI story summaries
- Add a chat-style “Talk to Grandma” experience

## Notes

- Reddit ingestion and backend routes were part of earlier prototypes
- The deployed Vercel version is static and runs fully in the browser
- Memory data is stored locally in the browser for this version

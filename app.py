from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


MemorySource = Literal["reddit", "instagram", "text", "url", "voice", "photo", "video", "whatsapp"]
MemoryKind = Literal["memory", "timeline_event", "recipe", "capsule", "person"]


@dataclass
class MemoryItem:
    id: int
    kind: MemoryKind
    title: str
    content: str
    source: MemorySource
    created_at: str
    person: str = "Grandparent"
    language: str = "en"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


DEFAULT_STATE = {
    "next_id": 1,
    "items": [],
    "people": [
        {
            "name": "Grandparent",
            "relationship": "Primary storyteller",
            "language": "en",
            "place": "Bengaluru",
        }
    ],
}

STATE = json.loads(json.dumps(DEFAULT_STATE))
INDEX_FILE = Path(__file__).resolve().with_name("index.html")

SEED_ITEMS = [
    MemoryItem(
        id=1,
        kind="memory",
        title="Childhood home",
        content="I grew up in a house with a mango tree in the courtyard and a tin roof that sang in the rain.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["childhood", "place", "home"],
        metadata={"prompt": "Where did you grow up?"},
    ),
    MemoryItem(
        id=2,
        kind="timeline_event",
        title="Birth in Village",
        content="Born in a small house with clay walls and a thatch roof in a quiet village near the river.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["birth", "village", "timeline"],
        metadata={"year": 1950, "track": "Places"},
    ),
    MemoryItem(
        id=3,
        kind="timeline_event",
        title="First Day of School",
        content="Walked 3 miles to the local primary school. Cried on the first day but quickly grew to love the feel of slates and chalk.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["school", "childhood", "timeline"],
        metadata={"year": 1956, "track": "Milestones"},
    ),
    MemoryItem(
        id=4,
        kind="timeline_event",
        title="Moved to Bengaluru",
        content="Moved from the village to Bengaluru in 1972 to look for work and stay with relatives.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["migration", "timeline"],
        metadata={"year": 1972, "track": "Places"},
    ),
    MemoryItem(
        id=5,
        kind="timeline_event",
        title="First Job at Textile Shop",
        content="Learned to measure silk, handle customer bargaining, and manage storage inventory at a small market shop.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["work", "timeline"],
        metadata={"year": 1975, "track": "Career"},
    ),
    MemoryItem(
        id=6,
        kind="timeline_event",
        title="Marriage",
        content="Married in a ceremony where the whole street helped with cooking, flowers, and seating guests.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["marriage", "timeline", "family"],
        metadata={"year": 1978, "track": "Milestones"},
    ),
    MemoryItem(
        id=7,
        kind="timeline_event",
        title="First Child Born",
        content="A healthy baby girl was born. The whole neighborhood came to celebrate and sing traditional blessings.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["child", "family", "timeline"],
        metadata={"year": 1980, "track": "Milestones"},
    ),
    MemoryItem(
        id=8,
        kind="timeline_event",
        title="Starting the Shop",
        content="Rented a tiny corner store to sell grains and spices. Worked long hours to establish the family business.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["business", "work", "timeline"],
        metadata={"year": 1985, "track": "Career"},
    ),
    MemoryItem(
        id=9,
        kind="timeline_event",
        title="Buying the Courtyard House",
        content="Finally bought our own home with a beautiful mango tree in the backyard and a tin roof.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["home", "timeline"],
        metadata={"year": 1992, "track": "Places"},
    ),
    MemoryItem(
        id=10,
        kind="timeline_event",
        title="First Grandchild Born",
        content="Welcomed the next generation into our lives. Holding them reminded us how beautifully the threads of time weave together.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["grandchild", "family", "timeline"],
        metadata={"year": 2005, "track": "Milestones"},
    ),
    MemoryItem(
        id=11,
        kind="recipe",
        title="Festival sweet",
        content="Take semolina, ghee, sugar, and cardamom. Roast slowly and finish with cashews.",
        source="voice",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["food", "recipe"],
        metadata={"occasion": "festival"},
    ),
    MemoryItem(
        id=12,
        kind="capsule",
        title="For your wedding day",
        content="Keep your family close and remember that love is built in small daily choices.",
        source="voice",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandparent",
        tags=["future", "capsule"],
        metadata={"unlock_date": "2035-01-01"},
    ),
    # Indian language stories
    MemoryItem(
        id=13,
        kind="memory",
        title="ಮೊದಲ ಸಂಬಳ (First Salary)",
        content="ನನ್ನ ಮೊದಲ ಸಂಬಳ ಬಂದ ದಿನ ಅಮ್ಮನಿಗೆ ಒಂದು ಸೀರೆ ತಂದೆ. ಅವರು ಅದನ್ನು ನೋಡಿ ಕಣ್ಣಿನಲ್ಲಿ ನೀರು ತುಂಬಿಕೊಂಡರು. 'ಇದಕ್ಕಿಂತ ದೊಡ್ಡ ಉಡುಗೊರೆ ಬೇಡ,' ಎಂದರು.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Family",
        language="kn",
        tags=["kannada", "work", "family", "multilingual"],
        metadata={"language": "Kannada"},
    ),
    MemoryItem(
        id=14,
        kind="memory",
        title="கோவில் திருவிழா (Temple Festival)",
        content="கோவில் திருவிழா வந்தால் கிராமமே விழித்துக் கொள்வது போல இருக்கும். நாதஸ்வரம், தீபங்கள், மலர் அலங்காரம் எங்கும் காணப்படும். எல்லோரும் சேர்ந்து உணவு அருந்துவோம்.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Family",
        language="ta",
        tags=["tamil", "festival", "community", "multilingual"],
        metadata={"language": "Tamil"},
    ),
    MemoryItem(
        id=15,
        kind="memory",
        title="పెళ్లి రోజు (Wedding Day)",
        content="మా పెళ్లి రోజున ఊరంతా ఒక కుటుంబంలా మారిపోయింది. ప్రతి ఇంటి వారు ఏదో ఒక ಕೆಲಸ చేశారు. ఆ రోజు ప్రేమ అంటే కలిసి ఉండడమే అని అర్థమైంది.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Family",
        language="te",
        tags=["telugu", "marriage", "family", "multilingual"],
        metadata={"language": "Telugu"},
    ),
    MemoryItem(
        id=16,
        kind="memory",
        title="প্রথম বর্ষার স্মৃতি (First Rain)",
        content="কলকাতার প্রথম বৃষ্টিতে আমরা সবাই ছাদে চলে যেতাম। মা খিচুড়ি আর ইলিশ মাছ ভাজত। সেই ভাজা মসলার আর ভিজে মাটির গন্ধ আজও মনে পড়ে।",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Grandmother",
        language="bn",
        tags=["bengali", "childhood", "rain", "multilingual"],
        metadata={"language": "Bengali"},
    ),
    MemoryItem(
        id=17,
        kind="memory",
        title="पहिला पगार (First Salary)",
        content="पहिल्या पगारातून आईला घेतलेली ती साडी आणि तिच्या डोळ्यात आलेले आनंदाचे अश्रू आजही माझ्या आठवणीत ताजे आहेत. तो क्षण सर्वात मौल्यवान होता।",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Father",
        language="mr",
        tags=["marathi", "work", "milestone", "multilingual"],
        metadata={"language": "Marathi"},
    ),
    MemoryItem(
        id=18,
        kind="memory",
        title="દિવાળીનો ગરબો (Diwali Garba)",
        content="નવરાત્રી અને દિવાળીમાં આખું ફળિયું સાથે મળીને ગરબા રમતું. માટીના દીવાની રોશની અને આપણો પારંપરિક પહેરવેશ તહેવારને જીવંત રાખતા હતા.",
        source="text",
        created_at="2026-06-29T00:00:00+00:00",
        person="Aunt",
        language="gu",
        tags=["gujarati", "festival", "culture", "multilingual"],
        metadata={"language": "Gujarati"},
    ),
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_state() -> dict[str, Any]:
    return json.loads(json.dumps(STATE))


def save_state(state: dict[str, Any]) -> None:
    STATE.clear()
    STATE.update(json.loads(json.dumps(state)))


def seed_state(state: dict[str, Any]) -> dict[str, Any]:
    if state["items"]:
        return state
    state["items"] = [asdict(item) for item in SEED_ITEMS]
    state["next_id"] = len(SEED_ITEMS) + 1
    return state


def add_item(state: dict[str, Any], item: MemoryItem) -> MemoryItem:
    item.id = state["next_id"]
    state["next_id"] += 1
    state["items"].insert(0, asdict(item))
    save_state(state)
    return item


def fetch_json(url: str) -> Any:
    req = Request(url, headers={"User-Agent": "MemoryWeaver/1.0"})
    with urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


_reddit_post_re = re.compile(r"^https?://(www\.)?reddit\.com/r/([^/]+)/comments/([^/]+)/?")
_reddit_short_re = re.compile(r"^https?://(www\.)?redd\.it/([^/?#]+)/?")


def ingest_reddit(url: str, person: str) -> list[MemoryItem]:
    if not (_reddit_post_re.match(url) or _reddit_short_re.match(url)):
        raise ValueError("Unsupported Reddit URL")
    payload = fetch_json(url.rstrip("/") + ".json")
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError("Unexpected Reddit payload")

    post = payload[0]["data"]["children"][0]["data"]
    items = [
        MemoryItem(
            id=0,
            kind="memory",
            title=post.get("title") or "Reddit post",
            content=post.get("selftext") or post.get("title") or "",
            source="reddit",
            created_at=now_iso(),
            person=person,
            tags=["reddit", f"subreddit:{post.get('subreddit')}"],
            metadata={
                "score": post.get("score"),
                "num_comments": post.get("num_comments"),
                "permalink": post.get("permalink"),
            },
        )
    ]

    for comment in payload[1]["data"]["children"][:20]:
        data = comment.get("data", {})
        body = data.get("body")
        if not body:
            continue
        items.append(
            MemoryItem(
                id=0,
                kind="memory",
                title=f"Comment by {data.get('author')}",
                content=body,
                source="reddit",
                created_at=now_iso(),
                person=person,
                tags=["reddit", "comment"],
                metadata={"score": data.get("score")},
            )
        )
    return items


def normalize_capture(source: str, payload: dict[str, Any], person: str) -> list[MemoryItem]:
    title = payload.get("title") or "Captured memory"
    text = payload.get("text") or payload.get("content") or ""
    if source == "text":
        if not text:
            raise ValueError("text is required")
        return [
            MemoryItem(
                id=0,
                kind=payload.get("kind", "memory"),
                title=title,
                content=text,
                source="text",
                created_at=now_iso(),
                person=person,
                language=payload.get("language", "en"),
                tags=payload.get("tags", ["manual"]),
                metadata=payload.get("metadata", {}),
            )
        ]
    if source == "reddit":
        url = payload.get("url")
        if not url:
            raise ValueError("url is required")
        return ingest_reddit(url, person)
    if source in {"voice", "photo", "video", "whatsapp", "instagram", "url"}:
        url = payload.get("url")
        if not url:
            raise ValueError("url is required")
        return [
            MemoryItem(
                id=0,
                kind=payload.get("kind", "memory"),
                title=title,
                content=text or f"Imported media reference from {url}",
                source=source,  # type: ignore[arg-type]
                created_at=now_iso(),
                person=person,
                language=payload.get("language", "en"),
                tags=payload.get("tags", [source, "media"]),
                metadata={**payload.get("metadata", {}), "url": url},
            )
        ]
    raise ValueError("Unsupported source")


def html_page() -> str:
    if INDEX_FILE.exists():
        return INDEX_FILE.read_text(encoding="utf-8")
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memory Weaver</title>
  <style>
    :root { color-scheme: light; --bg:#f4efe7; --panel:#fffaf2; --ink:#1f1a17; --muted:#6d625b; --accent:#8c5e3c; --accent2:#c78b5a; --line:#eadfcd; }
    * { box-sizing:border-box; }
    body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; background:
      radial-gradient(circle at top left, rgba(140,94,60,.12), transparent 30%),
      linear-gradient(180deg, #fbf7f1, #f3eadc 65%, #efe4d3); color:var(--ink); }
    .wrap { max-width: 1240px; margin: 0 auto; padding: 20px; }
    .hero { display:grid; grid-template-columns: 1.3fr .9fr; gap: 18px; align-items:stretch; }
    .card { background: rgba(255,250,242,.85); border:1px solid var(--line); border-radius:24px; box-shadow: 0 18px 60px rgba(62,40,25,.10); backdrop-filter: blur(8px); }
    .hero-main { padding: 28px; min-height: 280px; }
    .eyebrow { text-transform: uppercase; letter-spacing: .18em; font-size: 12px; color: var(--accent); font-weight: 700; }
    h1 { font-size: clamp(40px, 7vw, 74px); line-height: .95; margin: 12px 0 12px; letter-spacing:-.05em; }
    .lead { font-size: 18px; color: var(--muted); max-width: 62ch; }
    .stats { display:grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 22px; }
    .stat { padding: 14px; border-radius:18px; background: rgba(255,255,255,.55); border:1px solid var(--line); }
    .stat strong { display:block; font-size: 24px; }
    .hero-side { padding: 22px; display:flex; flex-direction:column; gap: 12px; }
    .pillrow { display:flex; flex-wrap:wrap; gap:8px; }
    .pill { padding:8px 12px; border-radius:999px; background: #fff; border:1px solid var(--line); font-size:13px; }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
    .panel { padding: 20px; }
    .panel h2 { margin: 0 0 12px; font-size: 24px; }
    label { display:block; font-size: 13px; color: var(--muted); margin: 12px 0 6px; }
    input, select, textarea { width: 100%; padding: 12px 14px; border-radius: 14px; border:1px solid var(--line); background:#fff; color:var(--ink); font: inherit; }
    textarea { min-height: 120px; resize: vertical; }
    button { cursor:pointer; border:0; border-radius: 14px; padding: 12px 16px; background: linear-gradient(135deg, var(--accent), var(--accent2)); color:#fff; font-weight: 700; }
    .toolbar { display:flex; gap:10px; flex-wrap:wrap; margin-top: 14px; }
    .list { display:grid; gap: 12px; }
    .item { padding: 16px; border-radius: 18px; border:1px solid var(--line); background: rgba(255,255,255,.7); }
    .itemhead { display:flex; justify-content:space-between; gap: 12px; align-items:flex-start; }
    .tagrow { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
    .tag { font-size: 12px; padding: 4px 8px; border-radius:999px; background:#f4eadc; color:#6d4b2a; }
    .muted { color: var(--muted); }
    .split { display:grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    .section-title { display:flex; justify-content:space-between; align-items:end; gap: 12px; margin-bottom: 12px; }
    .tiny { font-size: 12px; color: var(--muted); }
    @media (max-width: 900px) { .hero, .grid, .split { grid-template-columns:1fr; } .stats { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="card hero-main">
        <div class="eyebrow">Memory Weaver</div>
        <h1>Capture a life. Preserve the voice. Build the family archive.</h1>
        <p class="lead">A mobile-first web app for recording memories, importing stories, organizing timelines, and preparing future memory capsules.</p>
        <div class="stats" id="stats"></div>
      </div>
      <div class="card hero-side">
        <div>
          <strong>Core Modes</strong>
          <div class="pillrow" style="margin-top:10px">
            <div class="pill">Capture</div>
            <div class="pill">Timeline</div>
            <div class="pill">People Graph</div>
            <div class="pill">Recipe Vault</div>
            <div class="pill">Capsules</div>
            <div class="pill">Story Book</div>
          </div>
        </div>
        <div class="tiny">This MVP runs locally with no external packages and stores data in a JSON file.</div>
        <div class="card" style="padding:14px; background:#fff;">
          <div class="tiny">Prompt seed</div>
          <strong id="prompt"></strong>
        </div>
      </div>
    </section>

    <section class="card panel" style="margin-top:18px;">
      <div class="section-title">
        <h2>Actions</h2>
        <div class="tiny">These buttons now call real endpoints</div>
      </div>
      <div class="toolbar">
        <button type="button" id="refreshBtn">Refresh dashboard</button>
        <button type="button" id="exportBtn" style="background:#23495f;">Download JSON export</button>
        <button type="button" id="resetBtn" style="background:#7a3b3b;">Reset to demo data</button>
        <button type="button" id="addStoryBtn" style="background:#4d3f78;">Add sample story</button>
      </div>
    </section>

    <section class="grid">
      <div class="card panel">
        <div class="section-title">
          <h2>Capture Memory</h2>
          <div class="tiny">Text, Reddit, voice placeholders, media links</div>
        </div>
        <form id="captureForm">
          <label>Person</label>
          <input name="person" value="Grandparent">
          <label>Source</label>
          <select name="source">
            <option value="text">Text</option>
            <option value="reddit">Reddit URL</option>
            <option value="whatsapp">WhatsApp forward</option>
            <option value="voice">Voice recording</option>
            <option value="photo">Photo</option>
            <option value="video">Video</option>
            <option value="instagram">Instagram URL</option>
            <option value="url">Generic URL</option>
          </select>
          <label>Title</label>
          <input name="title" placeholder="Festival story">
          <label>Content</label>
          <textarea name="text" placeholder="Write the memory or summary here..."></textarea>
          <label>URL</label>
          <input name="url" placeholder="https://reddit.com/... or media link">
          <label>Tags, comma separated</label>
          <input name="tags" placeholder="childhood, food, village">
          <div class="toolbar">
            <button type="submit">Save memory</button>
            <button type="button" id="seedBtn" style="background:#2f4d3b;">Load demo data</button>
          </div>
        </form>
      </div>

      <div class="card panel">
        <div class="section-title">
          <h2>Story Tools</h2>
          <div class="tiny">Life story, capsules, recipes</div>
        </div>
        <div class="list" id="tools"></div>
      </div>
    </section>

    <section class="grid">
      <div class="card panel">
        <div class="section-title">
          <h2>Timeline</h2>
          <div class="tiny">Chronological life events</div>
        </div>
        <div class="list" id="timeline"></div>
      </div>
      <div class="card panel">
        <div class="section-title">
          <h2>Memory Library</h2>
          <div class="tiny">All captured items</div>
        </div>
        <div class="list" id="library"></div>
      </div>
    </section>
  </div>

  <script>
    const prompts = [
      "Where did you grow up? Describe your house.",
      "What did your mother cook for festivals?",
      "How did your family move from one place to another?",
      "What song did your parents sing to you?",
      "What was your first job like?"
    ];
    const formatDate = (s) => new Date(s).toLocaleString();
    const escapeHtml = (str) => String(str).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

    document.getElementById('prompt').textContent = prompts[Math.floor(Math.random() * prompts.length)];

    async function loadDashboard() {
      const res = await fetch('/api/dashboard');
      const data = await res.json();
      document.getElementById('stats').innerHTML = [
        ['Memories', data.stats.memories],
        ['People', data.stats.people],
        ['Recipes', data.stats.recipes]
      ].map(([label, value]) => `<div class="stat"><strong>${value}</strong><span class="muted">${label}</span></div>`).join('');
      document.getElementById('tools').innerHTML = `
        <div class="item"><strong>Life Story Builder</strong><div class="muted">Generate a chaptered family story from captured memories.</div></div>
        <div class="item"><strong>Talk to Grandma Mode</strong><div class="muted">Ask questions and answer only from stored memories.</div></div>
        <div class="item"><strong>Memory Capsules</strong><div class="muted">Future messages with unlock dates.</div></div>
        <div class="item"><strong>Recipe Vault</strong><div class="muted">Convert food memories into structured recipe cards.</div></div>
        <div class="item"><strong>WhatsApp Ingestion</strong><div class="muted">Paste a forwarded story or media URL and save it as a memory.</div></div>
      `;
      document.getElementById('timeline').innerHTML = data.timeline.map(item => `
        <div class="item">
          <div class="itemhead">
            <strong>${escapeHtml(item.title)}</strong>
            <span class="tiny">${escapeHtml(item.created_at)}</span>
          </div>
          <div class="muted">${escapeHtml(item.content)}</div>
        </div>
      `).join('') || '<div class="muted">No timeline events yet.</div>';
      document.getElementById('library').innerHTML = data.items.map(item => `
        <div class="item">
          <div class="itemhead">
            <strong>${escapeHtml(item.title)}</strong>
            <span class="tiny">${escapeHtml(item.kind)}</span>
          </div>
          <div class="muted">${escapeHtml(item.content)}</div>
          <div class="tagrow">${(item.tags || []).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}</div>
        </div>
      `).join('') || '<div class="muted">No memories yet.</div>';
    }

    document.getElementById('captureForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const payload = {
        person: form.get('person') || 'Grandparent',
        source: form.get('source'),
        title: form.get('title'),
        text: form.get('text'),
        url: form.get('url'),
        tags: String(form.get('tags') || '').split(',').map(s => s.trim()).filter(Boolean)
      };
      const res = await fetch('/api/ingest', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || 'Failed to save memory');
        return;
      }
      e.target.reset();
      await loadDashboard();
    });

    document.getElementById('seedBtn').addEventListener('click', async () => {
      await fetch('/api/seed', { method: 'POST' });
      await loadDashboard();
    });

    document.getElementById('refreshBtn').addEventListener('click', loadDashboard);

    document.getElementById('resetBtn').addEventListener('click', async () => {
      if (!confirm('Reset all saved memories back to the demo collection?')) return;
      await fetch('/api/reset', { method: 'POST' });
      await loadDashboard();
    });

    document.getElementById('exportBtn').addEventListener('click', async () => {
      const res = await fetch('/api/export');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'memory-weaver-export.json';
      a.click();
      URL.revokeObjectURL(url);
    });

    document.getElementById('addStoryBtn').addEventListener('click', async () => {
      const payload = {
        person: 'Grandparent',
        source: 'text',
        kind: 'memory',
        title: 'New family story',
        text: 'We sat together after dinner and listened to stories about the village, the first bicycle, and the day the rains came early.',
        tags: ['family', 'story', 'evening']
      };
      const res = await fetch('/api/ingest', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload)
      });
      if (res.ok) await loadDashboard();
    });

    loadDashboard();
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_html(html_page())
            return
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if parsed.path == "/api/dashboard":
            state = seed_state(load_state())
            items = state["items"]
            timeline = [item for item in items if item["kind"] == "timeline_event"]
            self._send_json(
                200,
                {
                    "stats": {
                        "memories": len(items),
                        "people": len(state["people"]),
                        "recipes": sum(1 for item in items if item["kind"] == "recipe"),
                    },
                    "items": items,
                    "timeline": timeline,
                    "people": state["people"],
                },
            )
            return
        if parsed.path == "/api/export":
            state = seed_state(load_state())
            payload = json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="memory-weaver-export.json"')
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self._send_json(404, {"detail": "Not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/seed":
            state = load_state()
            seed_state(state)
            self._send_json(200, {"status": "seeded"})
            return
        if parsed.path == "/api/reset":
            state = json.loads(json.dumps(DEFAULT_STATE))
            save_state(seed_state(state))
            self._send_json(200, {"status": "reset"})
            return
        if parsed.path != "/api/ingest":
            self._send_json(404, {"detail": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"detail": "Invalid JSON"})
            return

        state = seed_state(load_state())
        person = payload.get("person") or "Grandparent"
        source = payload.get("source")
        try:
            items = normalize_capture(source, payload, person)
            stored = [add_item(state, item) for item in items]
        except ValueError as exc:
            self._send_json(400, {"detail": str(exc)})
            return
        except (HTTPError, URLError, TimeoutError) as exc:
            self._send_json(502, {"detail": f"Fetch failed: {exc}"})
            return
        except Exception as exc:  # pragma: no cover
            self._send_json(500, {"detail": f"Unexpected error: {exc}"})
            return

        self._send_json(200, {"items": [asdict(item) for item in stored]})


def main() -> None:
    state = seed_state(load_state())
    save_state(state)
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Memory Weaver running on http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

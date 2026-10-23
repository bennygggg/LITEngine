"""Landing page — a small human-readable status page at the bare URL."""

import time
from datetime import datetime, timezone
from html import escape
from string import Template

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from config import get_settings
from services.embedder import embedder_service
from services.outcome_model import is_model_loaded

router = APIRouter(include_in_schema=False)

# Approximates process start; drives the "Up for" line.
_STARTED_AT = time.time()

# Colours come from the browser's own light/dark scheme (color-scheme + system
# colours), so there is no theme CSS to maintain. The page re-checks itself
# every minute.
_PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta http-equiv="refresh" content="60">
<title>$name</title>
<style>
  :root { --line: rgba(128, 128, 128, .35); --muted: rgba(128, 128, 128, 1); --ok: #16a34a; --warn: #d97706; }
  body { font: 16px/1.5 system-ui, sans-serif; margin: 0; padding: 32px 16px; }
  main { max-width: 34rem; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin: 0; }
  .lede { color: var(--muted); margin: .25rem 0 1.25rem; }
  .banner { border: 1px solid var(--line); border-left: 4px solid var(--tone); border-radius: 8px; padding: .75rem 1rem; font-weight: 600; margin-bottom: 1rem; }
  .card { border: 1px solid var(--line); border-radius: 8px; margin-bottom: 1rem; }
  .row { display: flex; gap: .75rem; align-items: baseline; padding: .65rem 1rem; }
  .row + .row { border-top: 1px solid var(--line); }
  .dot { width: .6rem; height: .6rem; border-radius: 50%; background: var(--tone); flex: none; }
  .label { font-weight: 600; min-width: 8.5rem; }
  .detail { color: var(--muted); }
  .ok { --tone: var(--ok); }
  .warn { --tone: var(--warn); }
  .facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); gap: 1rem; padding: .85rem 1rem; }
  .facts dt { color: var(--muted); font-size: .8rem; }
  .facts dd { margin: 0; font-weight: 600; }
  .buttons { display: flex; flex-wrap: wrap; gap: .5rem; }
  .btn { border: 1px solid var(--line); border-radius: 6px; padding: .45rem .9rem; text-decoration: none; color: inherit; font-weight: 600; }
  .btn:hover { border-color: currentColor; }
  .btn.primary { background: CanvasText; color: Canvas; border-color: CanvasText; }
  .foot { color: var(--muted); font-size: .8rem; margin-top: 1rem; }
</style>
</head>
<body>
<main>
  <h1>$name</h1>
  <p class="lede">Backend API for precedent search, fact extraction, argument graphs and outcome simulation in Indian law.</p>
  <div class="banner $banner_tone">$banner</div>
  <div class="card">$rows</div>
  <dl class="card facts">
    <div><dt>Version</dt><dd>$version</dd></div>
    <div><dt>Environment</dt><dd>$env</dd></div>
    <div><dt>Up for</dt><dd>$uptime</dd></div>
  </dl>
  <div class="buttons">$buttons</div>
  <p class="foot">Checked $checked UTC &middot; refreshes every minute</p>
</main>
</body>
</html>
""")


def _uptime(seconds: float) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _checks(settings) -> list[tuple[str, bool, str]]:
    """(label, healthy, detail) for each row of the status card."""
    index_loaded = not embedder_service.is_empty
    if index_loaded:
        docs = embedder_service.get_stats()["total_documents"]
        index_detail = f"{embedder_service.total_vectors} vectors across {docs} cases"
    else:
        index_detail = "Not loaded — search falls back to live Kanoon results"

    if embedder_service._use_hf_api:
        embed_ok, embed_detail = True, "Hugging Face Inference API"
    else:
        embed_ok = embedder_service._local_model is not None
        embed_detail = "Local MiniLM model" if embed_ok else "Local MiniLM model, not loaded yet"

    chat_ok = settings.hf_key_set
    chat_detail = settings.CHAT_MODEL if chat_ok else "No model key — answers quote the best excerpt"

    return [
        ("API", True, "Online"),
        ("Precedent index", index_loaded, index_detail),
        ("Outcome model", is_model_loaded(), "Trained classifier loaded" if is_model_loaded() else "Using the fallback heuristic"),
        ("Embeddings", embed_ok, embed_detail),
        ("Case chat", chat_ok, chat_detail),
    ]


def _button(href: str, text: str, primary: bool = False, external: bool = False) -> str:
    classes = "btn primary" if primary else "btn"
    target = ' target="_blank" rel="noopener"' if external else ""
    return f'<a class="{classes}" href="{escape(href)}"{target}>{escape(text)}</a>'


@router.get("/", response_class=HTMLResponse)
async def landing():
    settings = get_settings()
    checks = _checks(settings)
    degraded = [label for label, healthy, _ in checks if not healthy]

    rows = "".join(
        f'<div class="row {"ok" if healthy else "warn"}"><span class="dot"></span>'
        f'<span class="label">{escape(label)}</span><span class="detail">{escape(detail)}</span></div>'
        for label, healthy, detail in checks
    )

    buttons = [
        _button("/docs", "API docs", primary=True),
        _button("/health", "Health"),
        _button("/api/v1/health/ready", "Readiness"),
    ]
    frontend = next((o for o in settings.allowed_origins_list if o.startswith("https://")), "")
    if frontend:
        buttons.append(_button(frontend, "Open the app", external=True))

    page = _PAGE.substitute(
        name=escape(settings.APP_NAME),
        banner="All systems operational" if not degraded else "Degraded: " + ", ".join(degraded),
        banner_tone="ok" if not degraded else "warn",
        rows=rows,
        version=escape(settings.APP_VERSION),
        env=escape(settings.ENV),
        uptime=_uptime(time.time() - _STARTED_AT),
        buttons="".join(buttons),
        checked=datetime.now(timezone.utc).strftime("%H:%M:%S"),
    )
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})

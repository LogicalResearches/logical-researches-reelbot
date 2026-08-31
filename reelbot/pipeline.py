from __future__ import annotations

import html
from pathlib import Path

from .ai import GeminiClient
from .config import AppConfig
from .history import HistoryStore
from .models import ReelDraft
from .render import render_reel
from .scriptwriter import compose_caption, generate_script
from .selector import select_candidate
from .sources import article_from_url, demo_article, extract_article, fetch_candidates
from .util import slugify, utc_now, write_json
from .visuals import collect_visuals


def _preview_html(draft: ReelDraft, handle: str) -> str:
    caption = html.escape(draft.caption)
    source_url = html.escape(str(draft.article.url), quote=True)
    source_title = html.escape(draft.article.title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ReelBot draft — @{html.escape(handle)}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#07111f; --panel:#0e2033; --ink:#f7fbff; --accent:#36e1e9; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:radial-gradient(circle at top,#15344a,var(--bg) 42%); color:var(--ink); font:16px/1.5 system-ui,sans-serif; }}
    main {{ width:min(1040px,92vw); margin:36px auto 70px; display:grid; grid-template-columns:minmax(280px,430px) 1fr; gap:34px; }}
    video {{ width:100%; border-radius:24px; box-shadow:0 20px 70px #0009; background:#000; }}
    section {{ background:#0b1b2bcc; border:1px solid #ffffff18; border-radius:24px; padding:26px; align-self:start; }}
    .badge {{ color:var(--accent); font-weight:800; letter-spacing:.08em; font-size:.78rem; }}
    h1 {{ line-height:1.1; font-size:clamp(1.7rem,4vw,2.8rem); margin:.4rem 0 1rem; }}
    pre {{ white-space:pre-wrap; font:14px/1.5 system-ui,sans-serif; background:#06111d; border-radius:16px; padding:18px; max-height:390px; overflow:auto; }}
    a {{ color:var(--accent); }}
    button {{ border:0; border-radius:999px; padding:12px 18px; background:var(--accent); color:#05202a; font-weight:800; cursor:pointer; }}
    .note {{ color:#b9c8d5; font-size:.9rem; }}
    @media (max-width:760px) {{ main {{ grid-template-columns:1fr; }} video {{ max-height:70vh; }} }}
  </style>
</head>
<body>
<main>
  <video controls playsinline poster="{html.escape(draft.cover_path, quote=True)}">
    <source src="{html.escape(draft.media_path, quote=True)}" type="video/mp4">
  </video>
  <section>
    <div class="badge">SOURCE-GROUNDED DRAFT • {draft.duration_seconds:.1f} SECONDS</div>
    <h1>{html.escape(draft.script.headline)}</h1>
    <p><strong>Research source:</strong> <a href="{source_url}" rel="noreferrer">{source_title}</a></p>
    <pre id="caption">{caption}</pre>
    <button onclick="navigator.clipboard.writeText(document.getElementById('caption').innerText)">Copy caption</button>
    <p class="note">Review the source and Reel. To post this exact draft, run the “Publish current reviewed draft” action in GitHub.</p>
  </section>
</main>
</body>
</html>
"""


def generate_reel(
    *,
    config: AppConfig,
    output_dir: Path,
    work_root: Path,
    history_path: Path,
    topic_url: str | None = None,
    demo: bool = False,
    offline_visuals: bool = False,
) -> ReelDraft:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    history = HistoryStore(history_path)
    ai = GeminiClient(config)

    if demo:
        article = demo_article()
    elif topic_url:
        article = article_from_url(topic_url)
    else:
        candidates = fetch_candidates(config, history)
        article = extract_article(select_candidate(candidates, ai))

    script, script_validation = generate_script(article, config, ai)
    stamp = utc_now()
    draft_id = f"{stamp:%Y%m%d-%H%M}-{slugify(script.headline)}"
    work_dir = work_root / draft_id
    assets = collect_visuals(script, config, work_dir / "visuals", offline=offline_visuals)
    credits = [asset.credit for asset in assets if asset.credit]
    caption = compose_caption(script, article, credits, config)

    media_rel = f"reels/{draft_id}.mp4"
    cover_rel = f"covers/{draft_id}.jpg"
    media_path = output_dir / media_rel
    cover_path = output_dir / cover_rel
    media_validation = render_reel(
        script=script,
        article=article,
        assets=assets,
        ai=ai,
        config=config,
        work_dir=work_dir,
        output=media_path,
        cover=cover_path,
    )
    validation = {"script": script_validation, "media": media_validation}
    draft = ReelDraft(
        draft_id=draft_id,
        created_at=stamp,
        article=article,
        script=script,
        caption=caption,
        media_path=media_rel,
        cover_path=cover_rel,
        duration_seconds=float(media_validation["duration_seconds"]),
        width=int(media_validation["width"]),
        height=int(media_validation["height"]),
        visual_credits=credits,
        validation=validation,
    )
    write_json(output_dir / "draft.json", draft)
    (output_dir / "index.html").write_text(_preview_html(draft, config.page["handle"]), encoding="utf-8")
    history.add(str(article.url), article.title)
    return draft


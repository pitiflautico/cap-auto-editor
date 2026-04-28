"""Emit the index.html that HyperFrames renders for one video.

Strategy: every layer (b-roll asset OR subtitle word) is a positioned
absolute div under #stage. CSS sets all of them to opacity:0; a single
GSAP timeline turns each one on/off via `.set("#layer-N", {opacity:1})`
at start_s and `.set("#layer-N", {opacity:0})` at end_s. Video and
audio elements are explicitly seek-controlled in the same callbacks so
HyperFrames' headless Chromium has deterministic behaviour during
frame-by-frame capture.

A second iteration can swap opacity for `clip-path` reveals or GSAP
`.fromTo` transitions per `capcut_effect` — we keep the MVP simple and
deterministic.
"""
from __future__ import annotations

import json
from textwrap import dedent

from .contracts import CompositionLayer, CompositionPlan


_BASE_TEMPLATE = """\
<!doctype html>
<html>
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=__WIDTH__, height=__HEIGHT__" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@700;800&display=block"
        rel="stylesheet" />
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    html, body { width:__WIDTH__px; height:__HEIGHT__px; overflow:hidden;
                 background:#000; color:#fff;
                 font-family:'Montserrat', -apple-system, sans-serif; }
    #stage { position:relative; width:100%; height:100%; }
    .layer { position:absolute; opacity:0; will-change:opacity; }
    .layer.broll { left:0; top:0; width:100%; height:100%; }
    .layer.broll.split-top    { top:0; height:50%; }
    .layer.broll.split-bottom { top:50%; height:50%; }
    .layer.broll img,
    .layer.broll video { width:100%; height:100%; object-fit:cover;
                          background:#000; }
    .layer.subtitle { left:0; right:0; bottom:18%;
                       display:flex; justify-content:center; pointer-events:none; }
    .layer.subtitle .pill {
      background: rgba(0,0,0,0.78);
      color:#fff; padding:18px 36px;
      border-radius:36px;
      font-weight:800; font-size:96px; line-height:1;
      letter-spacing:0.5px;
      text-shadow:0 4px 12px rgba(0,0,0,0.45);
      max-width:88%;
      text-align:center;
      white-space:nowrap;
    }
  </style>
</head>
<body>
  <div id="root" data-composition-id="main"
       data-start="0" data-duration="__DURATION__"
       data-width="__WIDTH__" data-height="__HEIGHT__">
    <div id="stage">
__LAYERS_HTML__
    </div>
  </div>
__AUDIO_TAG__
  <script>
    window.__timelines = window.__timelines || {};
    const layers = __LAYER_TIMING_JSON__;
    const tl = gsap.timeline({ paused: true });
    layers.forEach((l, i) => {
      const el = document.getElementById("layer-" + i);
      if (!el) return;
      tl.set(el, { opacity: 1 }, l.start);
      tl.set(el, { opacity: 0 }, l.end);
      // For native <video> elements: seek + play at reveal so the
      // captured frame range is deterministic across the run.
      if (l.kind === "broll") {
        const v = el.querySelector("video");
        if (v) {
          tl.call(() => { try { v.currentTime = 0; v.play(); } catch (e) {} },
                   null, l.start);
          tl.call(() => { try { v.pause(); } catch (e) {} }, null, l.end);
        }
      }
    });
    window.__timelines["main"] = tl;
  </script>
</body>
</html>
"""


def _layer_div(layer: CompositionLayer, idx: int) -> str:
    """Render one layer as positioned div. Subtitle text is escaped."""
    if layer.kind == "subtitle":
        text = (layer.text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f'      <div id="layer-{idx}" class="layer subtitle">'
            f'<span class="pill">{text}</span></div>'
        )
    # b-roll layer
    klass = f'layer broll {layer.layout.replace("_","-")}' if layer.layout != "fullscreen" else "layer broll"
    asset = layer.asset_rel or ""
    if layer.asset_kind == "video":
        # `preload="auto"` + explicit <source> with type hint helps HF's
        # headless Chromium emit `loadedmetadata` reliably before the
        # capture deadline; the previous shorthand `<video src="…">`
        # was dropping metadata loads on ~30% of clips.
        inner = (
            f'<video muted preload="auto" playsinline crossorigin="anonymous">'
            f'<source src="{asset}" type="video/mp4" />'
            f'</video>'
        )
    else:
        inner = f'<img src="{asset}" alt="" loading="eager" />'
    return f'      <div id="layer-{idx}" class="{klass}">{inner}</div>'


def _layer_timing(layer: CompositionLayer) -> dict:
    """Trimmed JSON dict for the GSAP layer table."""
    return {
        "kind": layer.kind,
        "start": round(layer.start_s, 3),
        "end": round(layer.end_s, 3),
    }


def render_html(plan: CompositionPlan) -> str:
    """Produce the index.html string from a CompositionPlan."""
    layers = plan.layers
    layers_html = "\n".join(_layer_div(l, i) for i, l in enumerate(layers))
    timing = json.dumps([_layer_timing(l) for l in layers])

    audio_tag = ""
    if plan.audio_rel:
        audio_tag = (
            f'  <audio id="presenter_audio" src="{plan.audio_rel}" '
            'preload="auto" autoplay></audio>'
        )

    return (_BASE_TEMPLATE
            .replace("__WIDTH__",   str(plan.width))
            .replace("__HEIGHT__",  str(plan.height))
            .replace("__DURATION__", f"{plan.duration_s:.2f}")
            .replace("__LAYERS_HTML__",       layers_html)
            .replace("__LAYER_TIMING_JSON__", timing)
            .replace("__AUDIO_TAG__",          audio_tag))

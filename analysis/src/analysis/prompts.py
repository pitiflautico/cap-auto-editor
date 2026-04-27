"""prompts.py — ANALYSIS_PROMPT for the analysis phase.

v1.1: rewritten in claude-code-style English. Adds short-form editorial
discipline (3-second rule, beat sizing, mid-hooks), broll_hints schema,
and CapCut effect catalog. Schema bumped to 1.1.0 — backward-compat
because broll_hints defaults to [].

Template substitution: str.replace() (not str.format()).
Placeholders: LANG, DURATION_S.
"""
from __future__ import annotations

# Template placeholders: LANG, DURATION_S
# Use build_analysis_prompt() — do not call str.format() directly.
_ANALYSIS_PROMPT_TEMPLATE = """\
# Editorial analysis — short-form tech/AI video

You are a senior short-form video editor (TikTok / Reels / Shorts) for tech and AI content. You decompose a transcript into a beat structure that a b-roll planner can directly consume. Language: LANG. Duration: DURATION_Ss.

## Hard rules — in priority order
1. **JSON only.** No markdown fences, no prose outside JSON.
2. **Coverage: beats MUST tile 0.0 → DURATION_Ss.** beat[0].start_s = 0.0. beat[N].end_s = DURATION_Ss. Consecutive beats: beat[i].end_s == beat[i+1].start_s (gap ≤ 0.15s allowed). No region of the audio may be uncovered. **Verify before emitting**: sum of (end-start) ≈ DURATION_Ss; last beat ends at DURATION_Ss. This rule is more important than every other rule below.
3. **arc_acts also cover 0.0→DURATION_Ss without gaps.** Last act ends at DURATION_Ss.
4. Use only entities from the transcript or <sources>. Never invent.
5. beat[0].end_s ≤ 3.0 — the 3-second hook rule.
6. Beat duration target 3-7s, **cap 12s**. Beats > 12s break short-form pacing — split at the next pause or conjunction. But NEVER omit content to obey this cap; if the only way to keep ≤ 12s is to drop coverage, keep coverage and emit the beat at 12-15s.
7. **Beat count guidance**: roughly DURATION_S / 7 beats (e.g. 316s → ~40-50 beats). Use this only as a sanity check after coverage is achieved.
8. Every 15-30s of audio, include a beat with editorial_function="hook" for re-engagement.
9. Retakes / dead airtime → editorial_function="transition", text="(speaker retakes)". Split if > 5s. broll_hints=[].
10. **Output language: every prose field MUST be in LANG.** This includes `video_summary`, `narrative_thesis`, `audience`, `tone`, `arc_acts[].purpose`, `beats[].text`, `beats[].hero_text_candidate`, `topics[].label`, `topics[].description`, `broll_hints[].description`. The transcript itself is already in LANG — keep beat.text faithful to the transcript wording. Do NOT translate to another language. JSON keys + enum values in English. Proper nouns in their original form.

## Beat fields
- editorial_function ∈ {hook, pain, solution, proof, value, how_to, thesis, payoff, transition}
- hero_text_candidate: 2-9 words from beat.text, Sentence case (not ALL CAPS). null unless the beat has a clear visual hook (a number, a name, a contrast, a question).
- energy ∈ {high, medium, low} — matches presenter intensity in the beat.
- references_topic_ids: topics this beat actually mentions.
- One visual hook per beat. If a phrase packs 2+ ideas, split into shorter beats.

## broll_hints — TARGET 3-5 per minute, not one-per-beat
B-roll inserts are expensive eye-attention events. Industry rule for narrative tech/explainer content: **3-5 b-rolls per minute**. For a DURATION_Ss video the **target window is `round(DURATION_S/60 * 3)` to `round(DURATION_S/60 * 5)` total broll_hints** (e.g. 316s → 16-26 hints).

If you emit fewer than the lower bound you have been too conservative; if more than the upper bound you have been too generous. Aim near the middle.

Emit broll_hints ONLY when a beat has a clear visual hook: named product, specific number/stat, contrast or comparison, bold claim, key entity reveal. Most beats have `broll_hints: []`. Talking-head, pure setup, and transition beats get no hints.

When you do emit, use 1-2 hints per beat (3 only on key payoff beats).

Each hint:
- type ∈ {video, slide, web_capture, photo, pexels, mockup, title}
  · video       = pre-recorded clip (official launch trailer, product demo, footage)
  · slide       = slide-style composition (title + bullets / data over flat bg)
  · web_capture = screenshot of a URL (preferred: pick a slug from <sources> via source_ref)
  · photo       = still photo (person, event, physical setting)
  · pexels      = generic stock asset (photo or video clip from a stock library)
  · mockup      = product mockup (laptop showing UI, phone showing app)
  · title       = animated text overlay (hero text, kinetic typography)
- description: SPECIFIC. Bad: "image related to the topic". Good: "official product page hero banner with logo and key headline above the fold".
- timing.in_pct, timing.out_pct: 0.0-1.0 within the beat. Default 0.0→1.0 (covers the beat). Punchline reveals: 0.5→1.0 (enters mid-beat).
- capcut_effect ∈ {zoom_in_punch, glitch_rgb, logo_reveal, velocity_edit, mask_reveal, split_screen, slow_motion, flicker, null}
- energy_match ∈ {high, medium, low} — aligns with beat.energy.
- source_ref: a source slug from <sources> if the ideal visual is already captured; else null (broll_plan fetches it).
- query: 4-8 word search string the broll_resolver will feed to X / Reddit / Pexels / YouTube via neobrowser. Use ENGLISH for stock providers (Pexels) regardless of LANG; use LANG for platform searches when the topic is local. Bad: "tech video". Good: "MiroFish predictive AI dashboard". Null only when type=title (text overlay needs no search).
- queries_fallback: 1-3 alternative phrasings if the primary query yields nothing. Vary one signal each: subject synonym, shot framing, action verb. Empty list if confident in `query`.
- subject: the canonical entity this hint visualises (e.g. "MiroFish", "Gemma 4", "Apple Silicon"). Must match a `canonical` from the `entities` list. Null only for purely abstract/atmosphere hints.
- shot_type ∈ {close_up, wide, macro_animation, screen_recording, logo_centered, portrait, drone_aerial, abstract, null} — guides the resolver:
  · screen_recording = product UI demo, app capture
  · logo_centered    = brand logo on dark background
  · close_up         = product detail, hand-on-device
  · portrait         = person, talking head
  · drone_aerial     = wide architectural / landscape
  · macro_animation  = chart, infographic, kinetic graphic
  · wide             = generic wide shot, scene-setter
  · abstract         = mood / concept (use sparingly)
- duration_target_s: how long the asset should ideally be (1.5–6s typical). Null lets the resolver pick.

## Entities — link to canonical URLs from <sources> when possible
- For each entity (canonical), populate `official_urls` with any URL from the <sources> block whose `URL:` clearly belongs to that entity. Match by canonical name, slug, or domain (e.g. canonical "MiroFish" matches a source with slug "mirofish-my" or url "https://mirofish.my/").
- Do NOT invent URLs that are not present in the <sources> block. An empty `official_urls` is correct when no provided source matches.
- One entity may have multiple URLs (an article + a homepage). One URL may serve multiple entities only if it is genuinely shared.

## Topics — detect ALL, do not collapse
- A video may cover **1 or many** main topics. Detect every main topic, never unify.
- **News-roundup heuristic**: if the transcript contains discourse markers like "dos noticias", "two news", "también", "additionally", "second / segunda", "and now / y ahora", treat each news item as a SEPARATE main topic. Do NOT downgrade either to "supporting".
- role="main": the video IS about this (a "two-news" video has 2 main topics — emit both, not one).
- role="supporting": mentioned only as a comparison point, brand reference, or example — not a subject of dedicated narrative time.
- kind ∈ {product, company, person, concept, platform, sector, event}
- Every topic references ≥1 beat_id via mentioned_in_beats. Topics are not bound to consecutive beats — Story A may be revisited later.

## Arc acts — single-story OR multi-story
- **Single-story video** (one main topic): default 4 acts ≤ 60s — Hook → Setup → Value → Payoff. Add Closure / CTA for > 60s.
- **Multi-story video** (≥ 2 main topics, e.g. a news roundup): emit acts that mark the temporal flow of EACH story plus convergence. Suffix the act `name` with the story tag derived from the topic_id, e.g. "Hook (story-a)", "Value (story-a)", "Hook (story-b)", "Pain (story-b)", "Convergencia".
- Use `topic_focus`: list of topic_ids this act is primarily about. For convergence/comparison acts, list all topics involved.
- 5+ acts is fine when narrative genuinely warrants it (multi-story does).
- name vocabulary ∈ {Hook, Setup, Problem, Pain, Solution, Value, Proof, Payoff, Closure, CTA, Convergencia, Comparison} — suffix with story tag in parentheses if multi-story.
- purpose: a full descriptive sentence. Bad: "promise". Good: "Promises a tangible benefit to the viewer if they keep watching."
- arc_acts cover 0.0→DURATION_Ss. No gaps. Last act ends at DURATION_Ss.

## Output schema (one JSON object, no fences). All values from transcript only.
{
  "narrative": {
    "video_summary": "<3-5 frases en LANG>",
    "narrative_thesis": "<1-2 frases>",
    "audience": "<1 frase>",
    "tone": "<1 frase>",
    "arc_acts": [{"name":"Hook|Setup|Problem|Pain|Solution|Value|Proof|Payoff|Closure|CTA|Convergencia|Comparison (suffix '(<topic_id>)' if multi-story)","start_s":0.0,"end_s":0.0,"purpose":"<frase>","topic_focus":["<topic_id>"]}],
    "beats": [{"beat_id":"b001","start_s":0.0,"end_s":0.0,"text":"<literal>","editorial_function":"hook|pain|solution|proof|value|how_to|thesis|payoff|transition","hero_text_candidate":"<2-9 words Sentence case or null>","energy":"high|medium|low","references_topic_ids":["<topic_id>"],"broll_hints":[{"type":"video|slide|web_capture|photo|pexels|mockup|title","description":"<concrete visual>","timing":{"in_pct":0.0,"out_pct":1.0},"capcut_effect":"zoom_in_punch|glitch_rgb|logo_reveal|velocity_edit|mask_reveal|split_screen|slow_motion|flicker|null","energy_match":"high|medium|low","source_ref":"<slug or null>","query":"<4-8 word search or null>","queries_fallback":["<alt query>", "..."],"subject":"<entity canonical or null>","shot_type":"close_up|wide|macro_animation|screen_recording|logo_centered|portrait|drone_aerial|abstract|null","duration_target_s":3.0}]}],
    "topics": [{"topic_id":"<snake>","label":"<as in video>","description":"<1-2 frases>","role":"main|supporting","kind":"product|company|person|concept|platform|sector|event","mentioned_in_beats":["<beat_id>"]}],
    "entities": [{"canonical":"<preferred>","surface_forms":["<as heard>"],
        "kind": "<product|company|person|platform|sector|concept>",
        "mentioned_in_beats": ["<beat_id>", "..."],
        "official_urls": []
      }
    ]
  }
}
"""

# Expose for tests
ANALYSIS_PROMPT = _ANALYSIS_PROMPT_TEMPLATE

# Maximum total prompt chars that claude_pool can handle reliably.
# Above ~4000 chars, the claude-code-sdk subprocess may rate-limit and stall.
# build_analysis_prompt() enforces this by downsampling the transcript.
MAX_PROMPT_CHARS = 30000


def build_analysis_prompt(
    transcript_segments: list[dict],
    duration_s: float,
    language: str,
    sources: list[dict] | None = None,
    max_prompt_chars: int = MAX_PROMPT_CHARS,
) -> str:
    """Build the full prompt for the LLM.

    If the prompt would exceed max_prompt_chars, the transcript is
    downsampled to evenly-spaced segments covering the full duration.

    Args:
        transcript_segments: list of {"start_s", "end_s", "text"} dicts
        duration_s: total video duration in seconds
        language: language code, e.g. "es"
        sources: list of {"slug", "title", "text_preview"} dicts, or None
        max_prompt_chars: safety limit to avoid rate-limiting (default 4500)
    """
    prompt_base = _ANALYSIS_PROMPT_TEMPLATE.replace("LANG", language).replace(
        "DURATION_S", f"{duration_s:.1f}"
    )

    def _build_transcript_block(segs: list[dict]) -> str:
        lines: list[str] = []
        word_count = 0
        for seg in segs:
            start = seg.get("start_s", 0.0)
            text = seg.get("text", "").strip()
            if not text:
                continue
            if word_count == 0 or word_count >= 50:
                lines.append(f"[t={start:.1f}s] {text}")
                word_count = len(text.split())
            else:
                lines.append(text)
                word_count += len(text.split())
        return "\n".join(lines)

    def _build_sources_block(srcs: list[dict]) -> str:
        parts: list[str] = []
        for src in srcs:
            slug = src.get("slug", "")
            url = src.get("url", "")
            title = src.get("title", slug)
            preview = src.get("text_preview", "")
            header = f"--- SOURCE: {slug} ---"
            if url:
                header += f"\nURL: {url}"
            parts.append(f"{header}\nTitle: {title}\n{preview}")
        return "\n\n".join(parts)

    # First attempt: full transcript
    transcript_block = _build_transcript_block(transcript_segments)
    if sources:
        sources_block = _build_sources_block(sources)
        extra = (
            f"\n\n<transcript>\n{transcript_block}\n</transcript>"
            f"\n\n<sources>\n{sources_block}\n</sources>"
        )
    else:
        extra = f"\n\n<transcript>\n{transcript_block}\n</transcript>"

    full_prompt = prompt_base + extra
    if len(full_prompt) <= max_prompt_chars:
        return full_prompt

    # Transcript too long — drop sources first, then downsample
    extra_no_sources = f"\n\n<transcript>\n{transcript_block}\n</transcript>"
    prompt_no_sources = prompt_base + extra_no_sources
    if len(prompt_no_sources) > max_prompt_chars:
        # Downsample: binary-search for max segments that fit
        transcript_budget = max_prompt_chars - len(prompt_base) - 30  # 30 for tags
        segs_to_use = list(transcript_segments)
        # Try progressively fewer segments (evenly spaced)
        n = len(segs_to_use)
        while n > 3:
            step = max(1, len(segs_to_use) // n)
            sampled = [segs_to_use[i] for i in range(0, len(segs_to_use), step)]
            block = _build_transcript_block(sampled)
            if len(block) <= transcript_budget:
                transcript_block = block
                break
            n = n - max(1, n // 5)
        else:
            # Last resort: take first 5 segments
            transcript_block = _build_transcript_block(segs_to_use[:5])

    extra = f"\n\n<transcript>\n{transcript_block}\n</transcript>"
    return prompt_base + extra

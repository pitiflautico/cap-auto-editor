"""prompts.py — ANALYSIS_PROMPT for the analysis phase.

v2.0: the director no longer plans b-roll. Its only job is the
editorial skeleton (narrative, arc_acts, beats, topics, entities)
plus a single `visual_need / visual_anchor_type / visual_subject`
signal per beat. The dedicated `broll_planner` phase reads that and
emits the actual broll_hints with full source priority and queries.

Why splitting paid off: piling segmentation + entity extraction +
broll planning + capabilities + queries + capcut effects on one LLM
pass made the director cumple some rules and break others (notably
silently dropping hints on beats that named concrete features).

Placeholders use `string.Template` syntax: `${lang}` and `${duration_s}`.
The previous `str.replace("LANG", lang)` would also overwrite any
literal "LANG" elsewhere in the prompt — a footgun.
"""
from __future__ import annotations

from string import Template


# ── Prompt template ─────────────────────────────────────────────────


_ANALYSIS_PROMPT_TEMPLATE = """\
# Editorial analysis — short-form tech/AI video

You are a senior short-form video editor (TikTok / Reels / Shorts) for tech and AI content. Your job is the editorial skeleton: narrative, arc, beats, topics, entities. A second specialised agent handles b-roll planning, so you DO NOT emit b-roll hints here. Language: ${lang}. Duration: ${duration_s}s.

## Hard rules — in priority order
1. **JSON only.** No markdown fences, no prose outside JSON.
2. **Coverage: beats MUST tile 0.0 → ${duration_s}s.** beat[0].start_s = 0.0. beat[N].end_s = ${duration_s}. Consecutive beats: beat[i].end_s == beat[i+1].start_s (gap ≤ 0.15s allowed). No region of the audio may be uncovered. **Verify before emitting**: sum of (end-start) ≈ ${duration_s}; last beat ends at ${duration_s}. This rule is more important than every other rule below.
3. **arc_acts also cover 0.0→${duration_s}s without gaps.** Last act ends at ${duration_s}.
4. Use only entities from the transcript or <sources>. Never invent.
5. beat[0].end_s ≤ 3.0 — the 3-second hook rule.
6. Beat duration target 3-7s, **cap 12s**. Beats > 12s break short-form pacing — split at the next pause or conjunction. But NEVER omit content to obey this cap; if the only way to keep ≤ 12s is to drop coverage, keep coverage and emit the beat at 12-15s.
7. **Beat count guidance**: roughly ${duration_s} / 7 beats. Use this only as a sanity check after coverage is achieved.
8. Every 15-30s of audio, include a beat with editorial_function="hook" for re-engagement.
9. **Output language: every prose field MUST be in ${lang}.** This includes `video_summary`, `narrative_thesis`, `audience`, `tone`, `arc_acts[].purpose`, `beats[].text`, `beats[].hero_text_candidate`, `topics[].label`, `topics[].description`. The transcript itself is already in ${lang} — keep beat.text faithful to the transcript wording. Do NOT translate. JSON keys + enum values stay in English. Proper nouns in their original form.

## Beat fields
- editorial_function ∈ {hook, pain, solution, proof, value, how_to, thesis, payoff, transition}
- hero_text_candidate: 2-9 words from beat.text, Sentence case (not ALL CAPS). null unless the beat has a clear visual hook (a number, a name, a contrast, a question).
- energy ∈ {high, medium, low} — matches presenter intensity in the beat.
- references_topic_ids: topics this beat actually mentions.
- One visual hook per beat. If a phrase packs 2+ ideas, split into shorter beats.

### Faithful text + retakes
- `text` is the LITERAL transcript fragment. Do not paraphrase, normalise numbers, or rewrite. ASR mistakes stay in `text` — the polish phase already corrected what could be corrected; anything still wrong is signal, not noise to clean.
- For retakes / dead air / ASR garbage / pure silence, set `text` to whatever the transcript shows AND mark the situation in `flags`:
  · `speaker_retake` — speaker repeated a phrase or restarted
  · `asr_garbage` — transcript chars are clearly corrupt
  · `silence` — no narration, only ambient
  · `music_only` — music bed without speech
  Do NOT write synthetic placeholder text like "(speaker retakes)". Use flags so downstream phases can decide what to do without parsing prose.
- editorial_function="transition" plus `flags=["speaker_retake"]` is the correct pattern for retakes.

## visual_need — the ONLY broll signal you emit
For every beat decide whether b-roll is needed and, if so, what kind of anchor it should orient around. The downstream `broll_planner` agent will then plan the actual hint(s) — type, source, query, layout — using the entities + sources + visual_inventory available to it. Your job is editorial, not visual selection.

- visual_need ∈ {none, optional, required}
  · `required` — the beat names a concrete entity, metric, comparison, quote, platform, or feature, OR is a hook beat. Without b-roll the viewer is missing context.
  · `optional` — atmospheric / mood / connector beat where ambient b-roll would help but talking-head also works.
  · `none` — pure connector phrase, retake, transition without entity, dead air. Default for short transitions.
- visual_anchor_type ∈ {entity, metric, comparison, quote, platform, feature, mood, null}
  · `entity` — a named product / brand / company / person ("MiroFish", "GitHub", "Guo Hangjiang")
  · `metric` — a concrete number / money / percentage ("$4 million", "10 days", "20-year-old")
  · `comparison` — X vs Y, before/after, paid vs free
  · `quote` — an attributed phrase or thesis statement
  · `platform` — an external platform name (Twitter, Reddit, GitHub, App Store)
  · `feature` — a specific product capability ("god mode", "knowledge graph builder")
  · `mood` — atmospheric / abstract concept (only when visual_need=optional)
  · `null` — only when visual_need=none.
- visual_subject — the canonical entity / number / phrase that the b-roll should foreground. Examples: "MiroFish", "$4M raised in 24h", "GitHub trending", "fake Twitter and Reddit". Null when visual_need=none.

You do NOT pick the asset type, source_ref, query, layout, palette, or capcut effect. The broll_planner does that with full visibility of <sources> and visual_inventory. Your visual_need is a *brief*, not a *spec*.

### Coverage target
Aim for **at least 60% of beats to have visual_need ∈ {required, optional}** when the video is about a concrete product / topic with named entities. Connector phrases ("and then", "well") and retake transitions are the only "none" beats by default.

## Entities — link to canonical URLs from <sources> when possible
- For each entity (canonical), populate `official_urls` with any URL from the <sources> block whose `URL:` clearly belongs to that entity. Match by canonical name, slug, or domain (e.g. canonical "MiroFish" matches a source with slug "mirofish-my" or url "https://mirofish.my/").
- Do NOT invent URLs that are not present in the <sources> block. An empty `official_urls` is correct when no provided source matches.
- One entity may have multiple URLs (an article + a homepage). One URL may serve multiple entities only if it is genuinely shared.
- **Surface forms must be specific enough to disambiguate.** A bare one-word alias ("Qwen", "Claude") that could collide with a different version should NOT be a surface form when the canonical is versioned ("Qwen 3.6", "Claude Sonnet 4.6"). Prefer "Qwen 3.6" as both canonical AND surface form. The polish phase needs unambiguous surface_forms to safely substitute in the transcript.

## Topics — detect ALL, do not collapse
- A video may cover **1 or many** main topics. Detect every main topic, never unify.
- **News-roundup heuristic**: if the transcript contains discourse markers like "dos noticias", "two news", "también", "additionally", "second / segunda", "and now / y ahora", treat each news item as a SEPARATE main topic. Do NOT downgrade either to "supporting".
- role="main": the video IS about this (a "two-news" video has 2 main topics — emit both, not one).
- role="supporting": mentioned only as a comparison point, brand reference, or example — not a subject of dedicated narrative time.
- kind ∈ {product, company, person, concept, platform, sector, event}
- Every topic references ≥1 beat_id via mentioned_in_beats. Topics are not bound to consecutive beats — Story A may be revisited later.

### topic_id — deterministic snake_case
- Lowercase. Words separated by underscores. Preserve version numbers as digits with underscores instead of dots.
- Examples: "Qwen 3.6" → `qwen_3_6`. "GPT-5.5" → `gpt_5_5`. "Claude Sonnet 4.6" → `claude_sonnet_4_6`. "MiroFish" → `mirofish`.
- Strip trademark/legal suffixes: "Apple Inc." → `apple`.
- Two topics that disambiguate to the same id must add the disambiguator (e.g. `mirofish_app` vs `mirofish_company`).

## Arc acts — single-story OR multi-story
- **Single-story video** (one main topic): default 4 acts ≤ 60s — Hook → Setup → Value → Payoff. Add Closure / CTA for > 60s.
- **Multi-story video** (≥ 2 main topics, e.g. a news roundup): emit acts that mark the temporal flow of EACH story plus convergence. Suffix the act `name` with the story tag derived from the topic_id, e.g. "Hook (story-a)", "Value (story-a)", "Hook (story-b)", "Pain (story-b)", "Convergencia".
- Use `topic_focus`: list of topic_ids this act is primarily about. For convergence/comparison acts, list all topics involved.
- 5+ acts is fine when narrative genuinely warrants it (multi-story does).
- name vocabulary ∈ {Hook, Setup, Problem, Pain, Solution, Value, Proof, Payoff, Closure, CTA, Convergencia, Comparison} — suffix with story tag in parentheses if multi-story.
- purpose: a full descriptive sentence. Bad: "promise". Good: "Promises a tangible benefit to the viewer if they keep watching."
- arc_acts cover 0.0→${duration_s}s. No gaps. Last act ends at ${duration_s}.

## Output schema (one JSON object, no fences). All values from transcript only.
{
  "narrative": {
    "video_summary": "<3-5 frases en ${lang}>",
    "narrative_thesis": "<1-2 frases>",
    "audience": "<1 frase>",
    "tone": "<1 frase>",
    "arc_acts": [{"name":"Hook|Setup|Problem|Pain|Solution|Value|Proof|Payoff|Closure|CTA|Convergencia|Comparison (suffix '(<topic_id>)' if multi-story)","start_s":0.0,"end_s":0.0,"purpose":"<frase>","topic_focus":["<topic_id>"]}],
    "beats": [{"beat_id":"b001","start_s":0.0,"end_s":0.0,"text":"<literal>","editorial_function":"hook|pain|solution|proof|value|how_to|thesis|payoff|transition","hero_text_candidate":"<2-9 words Sentence case or null>","energy":"high|medium|low","references_topic_ids":["<topic_id>"],"visual_need":"none|optional|required","visual_anchor_type":"entity|metric|comparison|quote|platform|feature|mood|null","visual_subject":"<canonical entity / number / phrase or null>","flags":[],"broll_hints":[]}],
    "topics": [{"topic_id":"<snake_case_with_versions>","label":"<as in video>","description":"<1-2 frases>","role":"main|supporting","kind":"product|company|person|concept|platform|sector|event","mentioned_in_beats":["<beat_id>"]}],
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
# build_analysis_prompt() refuses to emit a prompt above this size —
# downsampling the transcript while still demanding full 0→duration
# coverage was a hard contradiction. If the limit is exceeded the
# caller must chunk the transcript and run analysis per window.
MAX_PROMPT_CHARS = 30000


class TranscriptTooLargeError(ValueError):
    """Raised when the transcript would push the prompt over MAX_PROMPT_CHARS.

    The previous build_analysis_prompt() silently downsampled in this
    case, which broke the coverage rule (the LLM was told to tile
    0→duration but only saw a fraction of the transcript).
    """


def build_analysis_prompt(
    transcript_segments: list[dict],
    duration_s: float,
    language: str,
    sources: list[dict] | None = None,
    max_prompt_chars: int = MAX_PROMPT_CHARS,
) -> str:
    """Build the full analysis prompt for the LLM.

    Args:
        transcript_segments: list of {"start_s", "end_s", "text"} dicts.
        duration_s: total video duration in seconds.
        language: language code, e.g. "es".
        sources: list of {"slug", "url", "title", "text_preview"} dicts, or None.
        max_prompt_chars: hard cap; we raise instead of downsampling.

    Raises:
        TranscriptTooLargeError when the assembled prompt exceeds
        max_prompt_chars. The pipeline should chunk the transcript and
        run analysis per window in that case.
    """
    # safe_substitute tolerates literal "$" sequences in the prompt
    # body (e.g. example metrics like "$4 million") without raising —
    # only `${lang}` and `${duration_s}` are rewritten.
    prompt_base = Template(_ANALYSIS_PROMPT_TEMPLATE).safe_substitute(
        lang=language, duration_s=f"{duration_s:.1f}",
    )

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
    if len(full_prompt) > max_prompt_chars:
        raise TranscriptTooLargeError(
            f"prompt would be {len(full_prompt)} chars > limit "
            f"{max_prompt_chars}. Chunk the transcript and run analysis "
            f"per window — silent downsampling broke the coverage rule."
        )
    return full_prompt


# ── helpers ────────────────────────────────────────────────────────


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

import json
import re
from utils.llm_client import LLMClient

llm = LLMClient()

# ══════════════════════════════════════════════
#  PROMPT LIBRARY — Proven YouTube frameworks
# ══════════════════════════════════════════════

HOOK_FRAMEWORKS = """
HOOK FRAMEWORKS (pick the most fitting one):
1. SHOCKING STAT:    "95% of people do X every day — and have no idea it's destroying them."
2. DIRECT CHALLENGE: "You think you're in control of your decisions. You're not."
3. CURIOSITY GAP:    "There's a bias in your brain right now that made you click this video."
4. BOLD CLAIM:       "This one mental trick is used by every cult, advertiser, and toxic person alive."
5. PATTERN INTERRUPT:"Stop. Before you do anything today — watch this first."
"""

HUMAN_TONE_RULES = """
HUMAN TONE RULES (follow every single one):
- Write like you're texting a smart friend, not reading a Wikipedia article
- Short sentences. Then a longer one to add depth. Then short again.
- Use "you" and "your" constantly — make it personal
- Replace academic words: "utilize" → "use", "individuals" → "people", "demonstrate" → "show"
- Add natural pauses with em-dashes — like this — for dramatic effect
- NO clichés: ban "let's dive in", "in today's video", "make sure to subscribe", "simply put", "in conclusion"
- Use real-world examples over abstract definitions
- Create open loops: mention something shocking early, resolve it later
- Vary sentence length: short. medium length flows better. one longer sentence can build real tension before the payoff.
"""

RETENTION_TACTICS = """
RETENTION TACTICS (inject throughout script):
- Pattern interrupt every 30s: sudden question, shocking stat, or bold statement
- Open loop at 0:20 — "And by the end of this video, you'll understand why most people never escape this."
- Re-hook at 0:45 — reference back to the opening hook
- Cliffhanger before each new point — "But here's where it gets really dark..."
- Power words: "secretly", "actually", "nobody tells you", "most people don't realize", "here's the truth"
- End each point with a real-world consequence that hits personally
"""

SECTION_STRUCTURE = """
SCRIPT STRUCTURE:
- hook (0-15s): One shocking statement. No intro. No fluff. Hit hard immediately.
- open_loop (15-30s): Tease what's coming. Create urgency. "By the end, you'll see why..."
- point_1 through point_N: Each point = punchy heading + 2-3 conversational sentences + real example
- callback (last 20s): Reference the hook. Deliver the payoff.
- outro (last 10s): ONE clear CTA. No begging. Make it feel earned.
"""

SCRIPT_SYSTEM_PROMPT = f"""You are a viral YouTube scriptwriter for a faceless psychology/facts channel.
Your videos get 60%+ retention because you write like a human who genuinely finds this stuff fascinating — not like a robot summarizing Wikipedia.

{HOOK_FRAMEWORKS}

{HUMAN_TONE_RULES}

{RETENTION_TACTICS}

{SECTION_STRUCTURE}

BANNED PHRASES (never use these):
"let's dive in", "in today's video", "make sure to subscribe", "simply put",
"in conclusion", "it's important to note", "fascinating", "intriguing", "delve",
"as we can see", "moving on", "first and foremost", "without further ado",
"let's explore", "now that we know", "stay tuned", "buckle up"

KOKORO TTS PUNCTUATION RULES (critical for natural voice):
- Use -- (double dash) for dramatic pauses: "Your brain is lying to you -- right now."
- Use -- for suspense build-up: "The worst part? -- You'll never see it coming."
- NEVER use ... (ellipsis) — use -- instead
- Keep sentences SHORT. Under 15 words each.
- Speed = 1.0 always. Never write [fast] or [slow] tags.

OUTPUT: VALID JSON ONLY. No markdown. No explanation. Raw JSON object.

Schema:
{{
  "title": "Punchy YouTube title, max 60 chars, creates curiosity gap, NOT clickbait that lies",
  "ab_title": "Alternative title using different angle, max 60 chars",
  "description": "SEO description 120-150 words. Include 3-5 natural keyword mentions. Add 5 hashtags at end.",
  "tags": ["tag1"...15 tags, mix of broad and specific],
  "bgm_mood": "one of: dark_suspense | lo_fi_chill | epic_dramatic | mysterious_ambient",
  "sections": [
    {{
      "section": "hook",
      "heading": "3-5 word punchy title shown on screen",
      "body": "Full voiceover text for this section. Conversational. Human. Max 3 sentences.",
      "duration_secs": 12,
      "icon_keyword": "brain",
      "emoji": "🧠"
    }}
  ],
  "total_duration_secs": 210
}}

CRITICAL: Each section MUST have both 'heading' (short, screen display) AND 'body' (full voiceover).
heading = what viewer READS on screen (3-5 bold words)
body = what narrator SAYS (2-4 conversational sentences)
These must be DIFFERENT. heading is punchy label, body is the explanation.
"""


# ══════════════════════════════════════════════
#  MAIN GENERATOR
# ══════════════════════════════════════════════

def generate_script(research_data: dict, style_hints: dict = None) -> dict:
    topic    = research_data["topic"]
    snippets = "\n".join(research_data["research_snippets"][:3])
    keywords = ", ".join(research_data["keywords"][:8])
    hints    = style_hints or {}
    fmt      = hints.get("video_format", "shocking_facts")
    title_f  = hints.get("title_formula", "dark_truth")
    length   = hints.get("target_length_secs", 210)

    # Calculate sections count from target length
    points_count = max(3, min(7, length // 30))

    user_msg = f"""Write a viral YouTube script about: "{topic}"

Research context:
{snippets[:900]}

Target keywords: {keywords}
Format: {fmt} | Title style: {title_f} | Target length: {length}s
Number of main points: {points_count}

REMEMBER:
- Hook must open with a stat or challenge, NOT a question starting with "Have you ever..."
- Each section heading = 3-5 words MAX (shown on screen)
- Each section body = 2-4 sentences of natural spoken voiceover
- No banned phrases
- Real examples over definitions
- Output ONLY raw JSON, zero markdown"""

    messages = [
        {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]

    raw = llm.complete(messages, max_tokens=3500, temperature=0.88)
    cleaned = re.sub(r"```json|```", "", raw).strip()

    try:
        data = json.loads(cleaned)
        data = _validate_and_fix(data, topic)
        print(f"[SCRIPT] Generated: {data['title']}")
        return data
    except json.JSONDecodeError as e:
        print(f"[SCRIPT] JSON parse failed: {e} — retrying...")
        return _retry_script(topic)


def _retry_script(topic: str) -> dict:
    messages = [
        {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Write viral YouTube script for: '{topic}'. "
                "Output ONLY a raw JSON object. No markdown. No backticks. "
                "Start your response with {{ and end with }}"
            )
        }
    ]
    raw     = llm.complete(messages, max_tokens=3500, temperature=0.7)
    cleaned = re.sub(r"```json|```", "", raw).strip()
    try:
        data = json.loads(cleaned)
        return _validate_and_fix(data, topic)
    except Exception:
        return _fallback_script(topic)


def _validate_and_fix(data: dict, topic: str) -> dict:
    """Ensure all required fields. Migrate old script_sections → sections."""

    # Migrate legacy format
    if "script_sections" in data and "sections" not in data:
        migrated = []
        for s in data["script_sections"]:
            text = s.get("text", "")
            words = text.split()
            heading = " ".join(words[:5]).upper() if words else s.get("section", "POINT").upper()
            migrated.append({
                "section":      s.get("section", "main"),
                "heading":      heading,
                "body":         text,
                "duration_secs": s.get("duration_secs", 30),
                "icon_keyword": s.get("icon_keyword", "brain"),
                "emoji":        s.get("emoji", "🧠"),
            })
        data["sections"] = migrated
        del data["script_sections"]

    data.setdefault("title",    f"The Truth About {topic} Nobody Talks About")
    data.setdefault("ab_title", f"{topic}: What They Don't Want You to Know")
    data.setdefault("description", (
        f"Discover the shocking psychological truth about {topic}. "
        f"These facts about {topic.lower()} will change how you see the world. "
        f"#{topic.replace(' ', '')} #psychology #mindblown"
    ))
    data.setdefault("tags", [
        topic.lower(), "psychology", "dark psychology", "mind tricks",
        "cognitive bias", "human behavior", "psychology facts",
        "mindblown", "viral facts", "brain facts", "manipulation",
        "self improvement", "mental health", "subconscious", "awareness"
    ])
    data.setdefault("bgm_mood", "dark_suspense")
    data.setdefault("total_duration_secs", 210)

    if "sections" not in data or not data["sections"]:
        data["sections"] = _default_sections(topic)

    # Ensure each section has heading + body
    for sec in data["sections"]:
        if "heading" not in sec:
            text  = sec.get("body", sec.get("text", ""))
            words = text.split()
            sec["heading"] = " ".join(words[:5]).upper() if words else "KEY POINT"
        if "body" not in sec:
            sec["body"] = sec.get("text", "")
        sec.setdefault("emoji", "🧠")
        sec.setdefault("icon_keyword", "brain")
        sec.setdefault("duration_secs", 30)

    return data


def _default_sections(topic: str) -> list:
    return [
        {
            "section": "hook", "heading": "YOUR BRAIN IS LYING",
            "body": f"Right now, as you read this, your brain is making decisions about {topic} — and you have zero control over it. That's not a metaphor. That's neuroscience.",
            "duration_secs": 12, "icon_keyword": "brain", "emoji": "🧠"
        },
        {
            "section": "open_loop", "heading": "HERE'S WHAT NOBODY SAYS",
            "body": f"By the end of this video, you're going to see {topic} completely differently. And once you do — you can't unsee it.",
            "duration_secs": 10, "icon_keyword": "eye", "emoji": "👁️"
        },
        {
            "section": "point_1", "heading": "THE HIDDEN PATTERN",
            "body": f"The first thing about {topic} that shocks people is how normal it looks from the outside. Everyone around you is affected — they just don't have a name for it.",
            "duration_secs": 35, "icon_keyword": "mask", "emoji": "🎭"
        },
        {
            "section": "point_2", "heading": "WHY IT WORKS ON YOU",
            "body": "Your brain isn't broken. It's running a program that was designed thousands of years ago. The problem? That program gets hijacked — every single day.",
            "duration_secs": 35, "icon_keyword": "lock", "emoji": "🔒"
        },
        {
            "section": "point_3", "heading": "THE REAL COST",
            "body": "Most people go their entire lives never realizing how much this has cost them. Relationships. Money. Decisions they thought were theirs to make.",
            "duration_secs": 35, "icon_keyword": "warning", "emoji": "⚠️"
        },
        {
            "section": "callback", "heading": "NOW YOU KNOW",
            "body": f"Remember the opening? Your brain lying to you about {topic}? Here's the part nobody tells you — awareness alone changes everything.",
            "duration_secs": 20, "icon_keyword": "light", "emoji": "💡"
        },
        {
            "section": "outro", "heading": "ONE LAST THING",
            "body": "If this changed how you think — share it with one person who needs to hear it. They might not thank you now. They will later.",
            "duration_secs": 10, "icon_keyword": "share", "emoji": "📤"
        },
    ]


def _fallback_script(topic: str) -> dict:
    return {
        "title":    f"Your Brain Is Lying About {topic}",
        "ab_title": f"{topic}: The Truth They Hide From You",
        "description": (
            f"The shocking psychological truth about {topic} that most people never discover. "
            f"These {topic.lower()} facts will permanently change how you make decisions. "
            f"#{topic.replace(' ','').lower()} #psychology #darkpsychology #mindblown #facts"
        ),
        "tags": [topic.lower(), "psychology", "dark psychology", "mind tricks",
                 "cognitive bias", "human behavior", "psychology facts", "mindblown",
                 "viral facts", "brain facts", "manipulation", "self improvement",
                 "mental health", "subconscious", "awareness"],
        "bgm_mood": "dark_suspense",
        "sections": _default_sections(topic),
        "total_duration_secs": 210,
    }


# ══════════════════════════════════════════════
#  TIMELINE + TEXT HELPERS
# ══════════════════════════════════════════════

def build_timeline(script_data: dict) -> list:
    """Convert sections into timestamp timeline for production_agent."""
    timeline     = []
    current_time = 0

    for sec in script_data.get("sections", []):
        mm = current_time // 60
        ss = current_time % 60
        timeline.append({
            "time":         f"{mm:02d}:{ss:02d}",
            "time_secs":    current_time,
            "icon_keyword": sec.get("icon_keyword", "brain"),
            "emoji":        sec.get("emoji", "🧠"),
            "heading":      sec.get("heading", ""),
            "text":         sec.get("body", ""),
            "section":      sec.get("section", "main"),
            "duration_secs": sec.get("duration_secs", 30),
        })
        current_time += sec.get("duration_secs", 30)

    return timeline


def get_full_script_text(script_data: dict) -> str:
    """
    Concatenate all section bodies into single voiceover string for TTS.
    Applies Kokoro punctuation hacks for natural breathing + emphasis.
    """
    raw = " ".join(
        s.get("body", s.get("text", ""))
        for s in script_data.get("sections", [])
    )
    return _apply_kokoro_hacks(raw)


def _apply_kokoro_hacks(text: str) -> str:
    """
    Gemini-confirmed Kokoro punctuation tricks:
    1. '...' → '--' for natural breathing pauses + suspense
    2. Sentence boundaries get '--' for breath between thoughts
    3. Numbers spelled out for better pronunciation
    4. Question marks preserved (Kokoro handles them well)
    """
    import re

    # 1. Replace ellipsis with double dash (breathing pause)
    text = text.replace('...', ' -- ')
    text = text.replace('…',   ' -- ')

    # 2. Add breathing pause after strong sentence endings mid-paragraph
    #    (not at the very end)
    text = re.sub(r'\. ([A-Z])', r'. -- \1', text)

    # 3. Em dash already good, normalize
    text = text.replace('—', ' -- ')

    # 4. Spell out common numbers for natural pronunciation
    number_map = {
        r'\b95\b': 'ninety-five',
        r'\b90\b': 'ninety',
        r'\b80\b': 'eighty',
        r'\b1\b':  'one',
        r'\b2\b':  'two',
        r'\b3\b':  'three',
    }
    for pattern, replacement in number_map.items():
        text = re.sub(pattern, replacement, text)

    # 5. Clean up multiple spaces/dashes
    text = re.sub(r'--\s*--', '--', text)
    text = re.sub(r'\s{2,}', ' ', text)

    return text.strip()

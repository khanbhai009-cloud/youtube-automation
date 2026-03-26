import json
import re
from utils.llm_client import LLMClient

llm = LLMClient()

SCRIPT_SYSTEM_PROMPT = """You are "Polymat" — a 0.01% elite content creator who makes viral YouTube videos.
You write scripts for USA audiences. Your style:
- Hook in first 5 seconds (shocking stat or question)
- Storytelling with psychological depth
- Short punchy sentences. Never boring.
- Target: 3-4 minutes (400-500 words)
- Niche: Psychology, Dark Facts, Mind-blowing Lists
- Tone: Confident, authoritative, slightly mysterious

OUTPUT MUST BE VALID JSON ONLY. No markdown, no explanation, just JSON.
Schema:
{
  "title": "YouTube video title (clickbait but honest, max 60 chars)",
  "description": "SEO description 150 words with keywords",
  "tags": ["tag1", "tag2", ...15 tags],
  "script_sections": [
    {
      "section": "hook",
      "text": "...",
      "duration_secs": 15,
      "icon_keyword": "brain"
    },
    ...more sections
  ],
  "thumbnail_prompt": "DALL-E prompt for viral thumbnail, plain white bg, bold text, illustrated icon",
  "total_duration_secs": 210
}"""

def generate_script(research_data: dict) -> dict:
    """
    Input: research_data from research_agent
    Output: full script + timeline dict
    """
    topic = research_data["topic"]
    snippets = "\n".join(research_data["research_snippets"][:3])
    keywords = ", ".join(research_data["keywords"][:8])

    user_msg = f"""Create a viral YouTube script about: "{topic}"

Research data:
{snippets[:800]}

Target keywords: {keywords}

Make it USA audience optimized. Hook must mention a shocking number or disturbing fact.
Remember: output ONLY valid JSON, no markdown backticks."""

    messages = [
        {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    raw = llm.complete(messages, max_tokens=3000, temperature=0.9)
    
    # Clean up any markdown fences
    cleaned = re.sub(r"```json|```", "", raw).strip()
    
    try:
        script_data = json.loads(cleaned)
        script_data = _validate_and_fix(script_data, topic)
        print(f"[SCRIPT] Generated: {script_data['title']}")
        return script_data
    except json.JSONDecodeError as e:
        print(f"[SCRIPT] JSON parse failed: {e}. Retrying with stricter prompt...")
        return _retry_script(topic, raw)


def _retry_script(topic: str, bad_response: str) -> dict:
    """Retry with example-based prompting."""
    messages = [
        {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Previous response had JSON errors. Create fresh script for: '{topic}'. ONLY output raw JSON object, nothing else."
        }
    ]
    raw = llm.complete(messages, max_tokens=3000, temperature=0.7)
    cleaned = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        # Ultimate fallback
        return _fallback_script(topic)


def _validate_and_fix(data: dict, topic: str) -> dict:
    """Ensure all required fields exist."""
    data.setdefault("title", f"Dark Truth About {topic} That Will Shock You")
    data.setdefault("description", f"Discover the shocking truth about {topic}. Mind-blowing facts most people don't know.")
    data.setdefault("tags", [topic.lower(), "psychology", "facts", "mindblown", "viral"])
    data.setdefault("thumbnail_prompt", f"Bold text '{topic.upper()}' on white background with illustrated brain icon")
    data.setdefault("total_duration_secs", 210)
    if "script_sections" not in data:
        data["script_sections"] = [{"section": "full", "text": topic, "duration_secs": 210, "icon_keyword": "brain"}]
    return data


def _fallback_script(topic: str) -> dict:
    return {
        "title": f"The Dark Truth About {topic}",
        "description": f"Mind-blowing psychological facts about {topic} that most people don't know about.",
        "tags": [topic.lower(), "psychology", "dark facts", "mindblown", "viral facts"],
        "script_sections": [
            {"section": "hook", "text": f"Did you know that {topic} affects 90% of people without them even realizing it?", "duration_secs": 15, "icon_keyword": "question"},
            {"section": "main", "text": f"Here's what psychology says about {topic} and why it matters in your daily life.", "duration_secs": 180, "icon_keyword": "brain"},
            {"section": "outro", "text": "If this blew your mind, share it. Most people will never know this.", "duration_secs": 15, "icon_keyword": "share"},
        ],
        "thumbnail_prompt": f"Bold text '{topic.upper()}' on white background with shocked face emoji",
        "total_duration_secs": 210,
    }


def build_timeline(script_data: dict) -> list:
    """
    Converts script_sections into a timestamp timeline.
    Returns: [{"time": "00:10", "icon_keyword": "brain", "text": "..."}, ...]
    """
    timeline = []
    current_time = 0
    for section in script_data.get("script_sections", []):
        mm = current_time // 60
        ss = current_time % 60
        timeline.append({
            "time": f"{mm:02d}:{ss:02d}",
            "time_secs": current_time,
            "icon_keyword": section.get("icon_keyword", "star"),
            "text": section.get("text", ""),
            "section": section.get("section", "main"),
            "duration_secs": section.get("duration_secs", 30),
        })
        current_time += section.get("duration_secs", 30)
    return timeline


def get_full_script_text(script_data: dict) -> str:
    """Concatenate all section texts into a single voiceover string."""
    return " ".join(s["text"] for s in script_data.get("script_sections", []))

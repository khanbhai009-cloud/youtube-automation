"""
agents/critic_agent.py

The Feedback Loop — evaluates scripts BEFORE production.

Role: An opinionated YouTube veteran who has seen 10,000 videos.
      Brutally rates whether this script will HOLD attention or lose it
      at the 30-second mark and never get it back.

Returns:
    {
        "approved":             bool,     # True = pass to production
        "score":                int,      # 1-10 quality score
        "hook_strength":        int,      # 1-10 hook rating
        "retention_risk":       str,      # "low" | "medium" | "high"
        "banned_phrases_found": list,     # any clichés detected
        "tone_assessment":      str,      # "conversational" | "textbook" | "mixed"
        "feedback":             str,      # plain english critique
        "rewrite_instructions": str,      # specific instructions for Script Agent
    }

Loop limit: 3 iterations max (controlled by orchestrator)
"""

import json
import re
from utils.llm_client import LLMClient
from utils.validator import validate_llm_output

llm = LLMClient()

CRITIC_SYSTEM = """You are a ruthless YouTube content critic with 10 years of data.
You review scripts for faceless psychology/dark education channels targeting US audiences 18-35.
You have seen thousands of scripts bomb at 30 seconds. You know exactly why.

YOUR JOB:
Rate the script on 10 dimensions. Be specific. Be brutal. Be constructive.

APPROVAL THRESHOLD: Score 7 or above = approved for production.
Below 7 = send back for rewrite with SPECIFIC instructions.

WHAT YOU LOOK FOR:
1. HOOK (0-15s): Does it punch hard enough in the first sentence? Or does it ease in gently?
2. CURIOSITY GAP: Does it tease something the viewer MUST know? Or does it explain too fast?
3. RETENTION TACTICS: Are there pattern interrupts every ~30s? Re-hooks? Cliffhangers?
4. TONE: Is it textbook/academic? Or does it feel like a smart friend talking?
5. BANNED PHRASES: "let's dive in", "in today's video", "simply put", "in conclusion", "it's important to note", "fascinating", "intriguing", "delve", "as we can see", "buckle up", "without further ado"
6. PACING: Short punchy sentences mixed with longer build-up? Or wall-of-text?
7. SPECIFICITY: Real examples and numbers? Or vague abstractions?
8. OPEN LOOPS: Does it create questions that keep viewer watching? Or resolve everything too fast?
9. AMERICAN ENGLISH: Any non-US phrases, Hindi words, Hinglish? Immediate fail.
10. EMOTIONAL ARC: Does it go from fear/shock → tension → revelation → empowerment?

OUTPUT: VALID JSON ONLY. No markdown. Raw JSON.

Schema:
{
  "approved": true | false,
  "score": 1-10,
  "hook_strength": 1-10,
  "retention_risk": "low" | "medium" | "high",
  "banned_phrases_found": ["phrase1", ...],
  "tone_assessment": "conversational" | "textbook" | "mixed",
  "feedback": "2-4 sentence plain English critique of what works and what fails",
  "rewrite_instructions": "If not approved: 3-5 SPECIFIC bullet points telling the Script Agent EXACTLY what to change. If approved: empty string."
}"""


def critique_script(script_data: dict, topic: str, iteration: int = 0) -> dict:
    """
    Evaluate a script. Returns structured feedback dict.

    Args:
        script_data:  Output from script_agent.generate_script()
        topic:        The video topic (for context)
        iteration:    Which critique loop we're on (0-2)
    """
    sections = script_data.get("sections", [])
    title    = script_data.get("title", "Unknown")

    script_preview = []
    for sec in sections:
        script_preview.append(
            f"[{sec.get('section','').upper()}] HEADING: {sec.get('heading','')}\n"
            f"BODY: {sec.get('body', sec.get('text',''))}"
        )
    full_preview = "\n\n".join(script_preview)

    total_words = sum(len(s.get("body","").split()) for s in sections)
    total_secs  = script_data.get("total_duration_secs", 210)

    user_msg = f"""Critique iteration #{iteration + 1}.

TITLE: {title}
TOPIC: {topic}
Total sections: {len(sections)} | Words: {total_words} | Target duration: {total_secs}s

=== FULL SCRIPT ===
{full_preview}

=== END SCRIPT ===

Score this script. Be specific about what fails. Output ONLY raw JSON."""

    messages = [
        {"role": "system", "content": CRITIC_SYSTEM},
        {"role": "user",   "content": user_msg},
    ]

    print(f"[CRITIC] Evaluating script (iteration {iteration + 1})...")
    raw = llm.complete(messages, max_tokens=800, temperature=0.4)

    # Validate and clean LLM output
    parsed = validate_llm_output(raw, phase="critic")

    if parsed.get("_used_failsafe"):
        print("[CRITIC] ⚠️ LLM output invalid — using safe fallback")
        return _fallback_critique(script_data)

    result = _validate_critique(parsed)
    _print_critique(result, title, iteration)
    return result


def _validate_critique(result: dict) -> dict:
    result.setdefault("approved",             True)
    result.setdefault("score",                7)
    result.setdefault("hook_strength",        6)
    result.setdefault("retention_risk",       "medium")
    result.setdefault("banned_phrases_found", [])
    result.setdefault("tone_assessment",      "mixed")
    result.setdefault("feedback",             "Script reviewed.")
    result.setdefault("rewrite_instructions", "")

    score = result.get("score", 7)
    if not isinstance(score, int):
        try:
            result["score"] = int(score)
        except Exception:
            result["score"] = 6

    if result["score"] < 7 and result.get("approved"):
        result["approved"] = False
    if result["score"] >= 7 and not result.get("approved"):
        result["approved"] = True

    return result


def _fallback_critique(script_data: dict) -> dict:
    sections = script_data.get("sections", [])
    hook_body = sections[0].get("body", "") if sections else ""
    banned = ["let's dive in", "in today's video", "simply put", "in conclusion",
              "fascinating", "intriguing", "delve", "buckle up"]
    found = [p for p in banned if p.lower() in hook_body.lower()]
    score = 8 if not found else 5

    return {
        "approved":             score >= 7,
        "score":                score,
        "hook_strength":        7 if score >= 7 else 4,
        "retention_risk":       "low" if score >= 7 else "high",
        "banned_phrases_found": found,
        "tone_assessment":      "mixed",
        "feedback":             "Critique system encountered an issue. Basic check passed." if score >= 7 else "Banned phrases detected in hook. Rewrite needed.",
        "rewrite_instructions": "" if score >= 7 else "Remove banned phrases. Start hook with a shocking stat or challenge.",
    }


def _print_critique(result: dict, title: str, iteration: int):
    status = "✅ APPROVED" if result["approved"] else "❌ REJECTED"
    print(f"""
[CRITIC] ═══ CRITIQUE RESULT (iteration {iteration + 1}) ═══
  Title:          {title}
  Status:         {status}
  Score:          {result['score']}/10
  Hook Strength:  {result['hook_strength']}/10
  Retention Risk: {result['retention_risk'].upper()}
  Tone:           {result['tone_assessment']}
  Banned Phrases: {result['banned_phrases_found'] or 'None found ✅'}
  Feedback:       {result['feedback']}
  Rewrite Notes:  {result['rewrite_instructions'] or '—'}
══════════════════════════════════════════""")

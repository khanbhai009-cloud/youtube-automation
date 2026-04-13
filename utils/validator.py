"""
utils/validator.py

Centralized LLM output validation and loop detection for YouTube AI Factory.

  validate_llm_output — strips markdown fences, parses JSON, validates required
      fields per phase, fills missing fields from FAIL_SAFES, applies phase-
      specific rules, and always returns a usable dict.  Never raises.

  loop_guard — detects repeated tool calls with identical arguments using a
      signature stored in state["tool_call_history"].
"""

from __future__ import annotations
import json
import logging
import re

logger = logging.getLogger(__name__)

# ── Required field schemas per phase ─────────────────────────────────────────

REQUIRED_SCHEMAS: dict[str, list[str]] = {
    "director":  ["niche", "topic", "angle", "upload_time", "confidence"],
    "research":  ["topic", "key_facts", "sources_found", "confidence"],
    "script":    ["hook", "scenes", "outro", "total_scenes"],
    "critic":    ["score", "pass", "issues"],
    "scene_dir": ["directives"],
}

# ── Fail-safe defaults per phase ─────────────────────────────────────────────

FAIL_SAFES: dict[str, dict] = {
    "director": {
        "niche":       "facts",
        "topic":       "5 Psychology Facts That Will Blow Your Mind",
        "angle":       "Shocking science",
        "upload_time": "20:00",
        "confidence":  0.5,
    },
    "research": {
        "key_facts": [
            "Humans forget 70% of information within 24 hours",
            "The brain processes images 60,000x faster than text",
            "Sleep deprivation affects cognition like being drunk",
        ],
        "sources_found": 0,
        "topic":        "Psychology Facts",
        "confidence":   0.4,
    },
    "script": {
        "hook":         "Your brain is lying to you -- right now.",
        "scenes":       [],
        "outro":        "Share this with someone who needs to hear it.",
        "total_scenes": 0,
    },
    "critic": {
        "score":  5,
        "pass":   False,
        "issues": ["Validation fallback — could not parse critic response"],
    },
    "scene_dir": {
        "directives": [],
    },
}

# ── Regex to strip unsafe chars from voiceover text ──────────────────────────

_VOICEOVER_STRIP_RE = re.compile(
    r"#\w*"           # hashtags
    r"|\*+"           # asterisks / bold markers
    r"|\[.*?\]"       # bracket content
    r"|https?://\S+"  # URLs
    r"|\*\*"          # residual double-asterisks
)


def _clean_voiceover(text: str) -> str:
    cleaned = _VOICEOVER_STRIP_RE.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


# ── Main validator ────────────────────────────────────────────────────────────

def validate_llm_output(raw: str, phase: str) -> dict:
    """
    Parse and validate LLM JSON output for a given pipeline phase.

    Rules applied regardless of phase:
      • Strips ```json / ``` fences before parsing
      • On JSONDecodeError → logs error, returns FAIL_SAFE for phase
      • Validates required fields; fills missing from FAIL_SAFES
      • Adds "_used_failsafe": True if any fallback was applied
      • Never raises an exception

    Phase-specific rules:
      • "script"   → strips #, *, [, ], http, ** from voiceover/body fields
      • "director" → validates niche in ["psychology","facts","listicles"],
                     defaults to "facts"
      • "critic"   → validates score is int 1-10, defaults to 5 if not
    """
    # ── Empty / None guard ────────────────────────────────────────────────────
    if not raw or not raw.strip():
        logger.error("[VALIDATOR] Empty LLM response for phase=%s", phase)
        return _make_failsafe(phase)

    # ── Strip markdown code fences ────────────────────────────────────────────
    cleaned = re.sub(r"```json\s*|```\s*", "", raw).strip()

    # ── Extract innermost JSON object or array ────────────────────────────────
    for open_c, close_c in [("{", "}"), ("[", "]")]:
        s = cleaned.find(open_c)
        if s != -1:
            e = cleaned.rfind(close_c)
            if e > s:
                cleaned = cleaned[s : e + 1]
                break

    # ── Parse JSON ────────────────────────────────────────────────────────────
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("[VALIDATOR] JSONDecodeError phase=%s: %s", phase, exc)
        return _make_failsafe(phase)

    if not isinstance(parsed, dict):
        logger.error("[VALIDATOR] Expected dict, got %s for phase=%s", type(parsed).__name__, phase)
        return _make_failsafe(phase)

    # ── LLM self-reported FAIL_SAFE ───────────────────────────────────────────
    if parsed.get("status") == "FAIL_SAFE":
        logger.warning("[VALIDATOR] LLM self-reported FAIL_SAFE phase=%s reason=%s",
                       phase, parsed.get("reason", ""))
        fs = _make_failsafe(phase)
        fs["_llm_failsafe_reason"] = parsed.get("reason", "")
        return fs

    used_failsafe = False

    # ── Fill missing required fields from FAIL_SAFES ──────────────────────────
    for field in REQUIRED_SCHEMAS.get(phase, []):
        if parsed.get(field) is None:
            default = FAIL_SAFES.get(phase, {}).get(field)
            if default is not None:
                parsed[field] = default
                used_failsafe = True
                logger.warning("[VALIDATOR] Filled missing field '%s' from failsafe (phase=%s)", field, phase)

    # ── Phase-specific validation ─────────────────────────────────────────────
    if phase == "director":
        allowed = ["psychology", "facts", "listicles"]
        if parsed.get("niche") not in allowed:
            logger.warning("[VALIDATOR] Invalid niche '%s' → 'facts'", parsed.get("niche"))
            parsed["niche"] = "facts"
            used_failsafe = True

    elif phase == "script":
        # Strip unsafe chars from top-level voiceover fields
        for field in ("hook", "outro"):
            if isinstance(parsed.get(field), str):
                parsed[field] = _clean_voiceover(parsed[field])
        # Clean body/voiceover inside scenes or sections lists
        for key in ("scenes", "sections"):
            for item in parsed.get(key) or []:
                if isinstance(item, dict):
                    for vf in ("body", "voiceover", "text"):
                        if isinstance(item.get(vf), str):
                            item[vf] = _clean_voiceover(item[vf])
        # Warn if hook exceeds 20 words
        hook = parsed.get("hook", "")
        if isinstance(hook, str) and len(hook.split()) > 20:
            logger.warning("[VALIDATOR] Hook exceeds 20 words in phase=script")

    elif phase == "critic":
        score = parsed.get("score")
        if not isinstance(score, int):
            try:
                parsed["score"] = int(score)
            except (TypeError, ValueError):
                parsed["score"] = 5
                used_failsafe = True
                logger.warning("[VALIDATOR] Invalid critic score → 5")
        score = parsed["score"]
        if not (1 <= score <= 10):
            parsed["score"] = max(1, min(10, score))
            used_failsafe = True
            logger.warning("[VALIDATOR] Critic score out of range → clamped to %d", parsed["score"])

    if used_failsafe:
        parsed["_used_failsafe"] = True

    return parsed


def _make_failsafe(phase: str) -> dict:
    """Return a copy of the fail-safe defaults for a given phase."""
    fs = dict(FAIL_SAFES.get(phase, {}))
    fs["_used_failsafe"] = True
    return fs


# ── Loop guard ────────────────────────────────────────────────────────────────

def loop_guard(state: dict, tool_name: str, args: dict) -> bool:
    """
    Detect repeated tool calls with identical arguments.

    Reads state["tool_call_history"] (defaults to []).
    Signature = "{tool_name}:{sorted(args.items())}".
    Returns True (loop detected) if signature appears 2+ times in history.
    Appends signature to history and updates state otherwise.
    """
    history: list = state.get("tool_call_history", [])
    signature = f"{tool_name}:{sorted(args.items())}"

    count = history.count(signature)
    if count >= 2:
        logger.warning("[LOOP GUARD] Loop detected — tool=%s seen %d times", tool_name, count + 1)
        return True

    history.append(signature)
    state["tool_call_history"] = history
    return False

"""
Director Agent — The autonomous brain.

Combines YouTube Analytics + real-time trends to make every strategic
decision BEFORE the pipeline runs:
  - Which niche & topic angle (weighted by niche_scores from analytics)
  - Video format (list / story / deep-dive / comparison)
  - Thumbnail style & A/B variant
  - Upload time (based on channel's best-performing hours)
  - Title formula (tested patterns vs fresh experiment)
  - Target audience mood
  - Whether to A/B test titles this video
"""

import json
import random
import re
from datetime import datetime, timezone

from utils.llm_client import LLMClient
from utils.validator import validate_llm_output
from agents.analytics_agent import fetch_channel_analytics, compute_niche_scores
from agents.research_agent import get_trending_topic

llm = LLMClient()

NICHES = ["psychology", "facts", "lists"]

DIRECTOR_SYSTEM = """You are the Director — an elite YouTube strategist with a 0.01% channel growth record.
You analyze data coldly and make binary, data-driven decisions.
Your job: given channel analytics + trending data, output a full strategic brief.

OUTPUT ONLY VALID JSON. No markdown, no explanation.
Schema:
{
  "niche": "psychology" | "facts" | "lists",
  "topic": "exact topic string",
  "video_format": "list_10" | "story_deep_dive" | "shocking_facts" | "comparison" | "psychological_breakdown",
  "target_length_secs": 180-240,
  "thumbnail_style": "dark_mystery" | "bold_number" | "split_face" | "plain_icon" | "minimal_text",
  "thumbnail_color_scheme": "red_black" | "white_bold" | "neon_dark" | "pastel_clean",
  "title_formula": "number_list" | "you_wont_believe" | "dark_truth" | "signs_you" | "what_happens_when",
  "ab_test": {
    "enabled": true | false,
    "title_a": "...",
    "title_b": "...",
    "hypothesis": "why title_b might outperform title_a"
  },
  "upload_hour_utc": 0-23,
  "reasoning": "2-3 sentence explanation of all decisions",
  "avoid_topics": ["topic1", "topic2"],
  "channel_diagnosis": "growing" | "plateauing" | "declining" | "new"
}"""


def _summarize_analytics(analytics: dict) -> str:
    """Convert raw analytics dict into a concise text summary for the LLM."""
    if not analytics.get("available"):
        return "Channel analytics unavailable (new channel or API error). No historical data."

    top = analytics.get("top_videos", [])
    best_hours = analytics.get("best_hours_utc", [])
    recent_titles = analytics.get("recent_titles", [])

    lines = []

    if top:
        best = top[0]
        lines.append(f"Top video last {analytics['period_days']}d: {best['views']} views, {best['avg_view_pct']}% avg retention, {best['likes']} likes")
        avg_views = sum(v["views"] for v in top) / len(top)
        lines.append(f"Average views across top 5: {int(avg_views)}")
        avg_ret = sum(v["avg_view_pct"] for v in top) / len(top)
        lines.append(f"Average retention: {avg_ret:.1f}%")

    if best_hours:
        best_h = best_hours[0]["hour_utc"]
        lines.append(f"Best upload hour UTC: {best_h:02d}:00 ({(best_h - 5) % 24:02d}:00 EST)")

    if recent_titles:
        lines.append(f"Recent video titles: {' | '.join(recent_titles[:5])}")

    traffic = analytics.get("traffic_sources", {})
    if traffic:
        top_source = max(traffic, key=traffic.get)
        lines.append(f"Top traffic source: {top_source} ({traffic[top_source]} views)")

    return "\n".join(lines) if lines else "Minimal data available."


def _summarize_trends(trends_by_niche: dict) -> str:
    """Summarize trending topics across all niches."""
    lines = []
    for niche, data in trends_by_niche.items():
        topic = data.get("topic", "N/A")
        kws = ", ".join(data.get("keywords", [])[:5])
        lines.append(f"{niche.upper()}: trending='{topic}' | keywords: {kws}")
    return "\n".join(lines)


def _pick_weighted_niche(niche_scores: dict) -> str:
    """
    Pick a niche weighted by performance scores.
    Niches with score > 7 get 2x probability.
    If niche_scores is empty, pick evenly from NICHES.
    """
    if not niche_scores:
        return random.choice(NICHES)

    weighted_pool = []
    for niche in NICHES:
        score = niche_scores.get(niche, 5.0)
        weight = 2 if score > 7.0 else 1
        weighted_pool.extend([niche] * weight)

    return random.choice(weighted_pool)


def run_director(niche_scores: dict = None) -> dict:
    """
    Main entry point. Returns a full StrategyBrief dict.

    Args:
        niche_scores: Optional dict of per-niche performance scores from analytics
                      e.g. {"facts": 8.2, "psychology": 6.1}
    """
    print("\n╔══════════════════════════════════════╗")
    print("║   DIRECTOR AGENT — THINKING...  ║")
    print("╚══════════════════════════════════════╝")

    niche_scores = niche_scores or {}

    # ── Step 1: Fetch analytics ───────────────────────────────────────────
    print("[DIRECTOR] Fetching channel analytics...")
    analytics = fetch_channel_analytics(days=28)

    # ── Step 1b: Compute niche scores if not provided ──────────────────────
    if not niche_scores:
        niche_scores = compute_niche_scores(analytics)

    # ── Step 2: Scan trends across all niches in parallel ─────────────────
    print("[DIRECTOR] Scanning trends across all niches...")
    trends = {}
    for niche in NICHES:
        try:
            trends[niche] = get_trending_topic(niche)
        except Exception as e:
            print(f"[DIRECTOR] Trend fetch failed for {niche}: {e}")
            trends[niche] = {"topic": niche.title(), "keywords": [niche]}

    # ── Step 2b: Log niche score weighting ────────────────────────────────
    preferred_niche = _pick_weighted_niche(niche_scores)
    score_info = f"score={niche_scores.get(preferred_niche, 'N/A')}" if niche_scores else "no scores"
    print(f"[DIRECTOR] Preferred niche (weighted): {preferred_niche} ({score_info})")

    # ── Step 3: Build context for LLM ─────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    day_of_week = now_utc.strftime("%A")
    hour_utc = now_utc.hour

    analytics_summary = _summarize_analytics(analytics)
    trends_summary = _summarize_trends(trends)

    niche_scores_block = ""
    if niche_scores:
        score_lines = [f"  {n}: {s:.1f}/10" for n, s in sorted(niche_scores.items(), key=lambda x: -x[1])]
        niche_scores_block = "\n\n═══ NICHE PERFORMANCE SCORES (from analytics) ═══\n" + "\n".join(score_lines)
        niche_scores_block += f"\nRecommended niche (highest score): {preferred_niche}"

    user_msg = f"""Current context:
- Date/Time UTC: {now_utc.strftime('%Y-%m-%d %H:%M')} ({day_of_week})
- Current hour UTC: {hour_utc}

═══ CHANNEL ANALYTICS (last 28 days) ═══
{analytics_summary}{niche_scores_block}

═══ TRENDING TOPICS RIGHT NOW ═══
{trends_summary}

Based on this data, decide the complete strategy for the next video.
Pick the niche and topic that will perform best given both channel history and current trends.
Set upload_hour_utc to the channel's best-performing hour (from analytics).
If analytics unavailable, use 1 (8 PM EST).
Enable A/B testing if the channel is plateauing or we want to test a new title formula.
Output ONLY raw JSON."""

    messages = [
        {"role": "system", "content": DIRECTOR_SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    # ── Step 4: LLM makes the call ────────────────────────────────────────
    print("[DIRECTOR] LLM analyzing data and making strategic decisions...")
    raw = llm.complete(messages, max_tokens=1500, temperature=0.6, task_type="logical")

    # ── Step 4b: Validate LLM output ──────────────────────────────────────
    parsed = validate_llm_output(raw, phase="director")

    if parsed.get("_used_failsafe"):
        print("[DIRECTOR] ⚠️ Used failsafe defaults for director output")

    brief = _validate_brief(parsed, trends, analytics, preferred_niche)
    _print_brief(brief)

    return {
        "strategy_brief":  brief,
        "analytics_raw":   analytics,
        "trends_raw":      trends,
        "niche_scores":    niche_scores,
        "_director_used_failsafe": bool(parsed.get("_used_failsafe")),
    }


def _validate_brief(brief: dict, trends: dict, analytics: dict, preferred_niche: str = "psychology") -> dict:
    """Ensure all required fields exist and values are valid."""
    valid_niches = ["psychology", "facts", "lists"]
    if brief.get("niche") not in valid_niches:
        brief["niche"] = preferred_niche if preferred_niche in valid_niches else "psychology"

    # Use actual trending topic for the chosen niche if LLM's topic is vague
    niche = brief["niche"]
    if not brief.get("topic") or len(brief["topic"]) < 5:
        brief["topic"] = trends.get(niche, {}).get("topic", "Dark Psychology")

    # Validate upload hour
    hour = brief.get("upload_hour_utc", 1)
    if not isinstance(hour, int) or not (0 <= hour <= 23):
        best_hours = analytics.get("best_hours_utc", [{"hour_utc": 1}])
        hour = best_hours[0]["hour_utc"] if best_hours else 1
        brief["upload_hour_utc"] = hour

    # Ensure A/B test structure
    if "ab_test" not in brief:
        brief["ab_test"] = {"enabled": False, "title_a": "", "title_b": "", "hypothesis": ""}

    brief.setdefault("video_format", "shocking_facts")
    brief.setdefault("thumbnail_style", "plain_icon")
    brief.setdefault("thumbnail_color_scheme", "white_bold")
    brief.setdefault("title_formula", "dark_truth")
    brief.setdefault("target_length_secs", 210)
    brief.setdefault("reasoning", "Data-driven decision by Director Agent.")
    brief.setdefault("avoid_topics", [])
    brief.setdefault("channel_diagnosis", "new")
    return brief


def _print_brief(brief: dict):
    print(f"""
[DIRECTOR] STRATEGY BRIEF
  Niche:          {brief['niche'].upper()}
  Topic:          {brief['topic']}
  Format:         {brief['video_format']}
  Length:         {brief['target_length_secs']}s
  Thumbnail:      {brief['thumbnail_style']} / {brief['thumbnail_color_scheme']}
  Title formula:  {brief['title_formula']}
  Upload (UTC):   {brief['upload_hour_utc']:02d}:00
  A/B Test:       {'ON: ' + brief['ab_test'].get('title_b','') if brief['ab_test'].get('enabled') else 'Off'}
  Diagnosis:      {brief['channel_diagnosis']}
  Reasoning:      {brief['reasoning']}""")


def _fallback_brief(trends: dict, analytics: dict) -> dict:
    """Safe fallback if LLM fails entirely."""
    best_hours = analytics.get("best_hours_utc", [{"hour_utc": 1}])
    upload_hour = best_hours[0]["hour_utc"] if best_hours else 1
    topic = trends.get("psychology", {}).get("topic", "Dark Psychology")
    brief = {
        "niche": "psychology",
        "topic": topic,
        "video_format": "psychological_breakdown",
        "target_length_secs": 210,
        "thumbnail_style": "plain_icon",
        "thumbnail_color_scheme": "white_bold",
        "title_formula": "dark_truth",
        "ab_test": {"enabled": False, "title_a": "", "title_b": "", "hypothesis": ""},
        "upload_hour_utc": upload_hour,
        "reasoning": "Fallback strategy: psychology is highest-RPM niche.",
        "avoid_topics": [],
        "channel_diagnosis": "new",
    }
    return {"strategy_brief": brief, "analytics_raw": analytics, "trends_raw": trends, "niche_scores": {}}

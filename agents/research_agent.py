import os
import json
import random
from tavily import TavilyClient
from pytrends.request import TrendReq

_tavily_client = None

def _get_tavily():
    global _tavily_client
    if _tavily_client is None:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("TAVILY_API_KEY not set")
        _tavily_client = TavilyClient(api_key=api_key)
    return _tavily_client

NICHE_SEEDS = {
    "psychology": [
        "dark psychology", "manipulation tactics", "cognitive biases",
        "human behavior", "subconscious mind", "social engineering",
        "emotional intelligence", "narcissism signs", "persuasion psychology"
    ],
    "facts": [
        "mind blowing facts", "science facts", "history facts",
        "space facts", "animal facts", "human body facts",
        "world records", "ancient civilization facts"
    ],
    "lists": [
        "things you didn't know", "habits of successful people",
        "signs of high intelligence", "life changing habits",
        "productivity hacks", "psychological tricks",
        "things rich people do differently", "red flags in people"
    ],
}

def get_trending_topic(niche: str = "psychology") -> dict:
    """
    Returns: { topic, keywords, research_snippets, search_query }
    """
    niche = niche.lower()
    seeds = NICHE_SEEDS.get(niche, NICHE_SEEDS["psychology"])

    # Step 1: Get Google Trends hot queries
    try:
        pytrends = TrendReq(hl="en-US", tz=-300)  # USA timezone offset
        seed = random.choice(seeds)
        pytrends.build_payload([seed], cat=0, timeframe="now 7-d", geo="US")
        related = pytrends.related_queries()
        top_queries = related[seed]["top"]
        if top_queries is not None and len(top_queries) > 0:
            trending_kw = top_queries["query"].iloc[0]
        else:
            trending_kw = seed
        print(f"[RESEARCH] Google Trends top query: {trending_kw}")
    except Exception as e:
        print(f"[RESEARCH] Google Trends failed: {e}. Using seed directly.")
        trending_kw = random.choice(seeds)

    # Step 2: Deep research via Tavily
    try:
        search_query = f"{trending_kw} psychology facts 2025"
        results = _get_tavily().search(
            query=search_query,
            search_depth="advanced",
            max_results=5,
            include_answer=True,
        )
        snippets = [r["content"][:400] for r in results.get("results", [])]
        answer = results.get("answer", "")
        keywords = _extract_keywords(trending_kw, snippets)

        print(f"[RESEARCH] Topic finalized: {trending_kw} | Keywords: {keywords[:3]}")
        return {
            "topic": trending_kw.title(),
            "keywords": keywords,
            "research_snippets": snippets,
            "search_query": search_query,
            "tavily_answer": answer,
        }
    except Exception as e:
        print(f"[RESEARCH] Tavily failed: {e}")
        return {
            "topic": trending_kw.title(),
            "keywords": [trending_kw, niche, "psychology"],
            "research_snippets": [],
            "search_query": trending_kw,
            "tavily_answer": "",
        }

def _extract_keywords(base: str, snippets: list) -> list:
    """Simple keyword extraction from snippets."""
    import re
    text = " ".join(snippets).lower()
    words = re.findall(r'\b[a-z]{4,}\b', text)
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    stopwords = {"this", "that", "with", "from", "they", "their", "have",
                 "will", "when", "what", "which", "some", "more", "also",
                 "been", "than", "then", "into", "over", "your", "about"}
    sorted_kw = sorted(freq, key=freq.get, reverse=True)
    filtered = [w for w in sorted_kw if w not in stopwords]
    result = [base] + filtered[:14]
    return list(dict.fromkeys(result))[:15]

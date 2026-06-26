"""Communication-style & mood memory (#9). Deterministic, key-less lexicon
baseline — works in ANY domain (support, tutoring, booking, healthcare, sales).
A small model can replace analyze() later for higher accuracy; the storage and
mood-trend logic stay the same.

Output feeds two things: (1) transient style tags stored with recent events,
(2) a mood EMA + trend the agent uses to adapt tone and notice when someone's
mood is sliding. Style tags are not durable graph edges."""
from __future__ import annotations
import math, re
from typing import Dict, List

FORMAL = {"please", "thank", "thanks", "would", "could", "kindly", "regards",
          "sincerely", "appreciate", "apologies", "apologize", "dear"}
CASUAL = {"hey", "yeah", "yep", "nope", "lol", "gonna", "wanna", "cool", "u",
          "ur", "haha", "dunno", "kinda", "sup", "omg", "btw"}
POS = {"great", "good", "love", "happy", "thanks", "awesome", "excellent",
       "perfect", "glad", "appreciate", "nice", "wonderful", "amazing", "yay"}
NEG = {"bad", "hate", "angry", "upset", "annoyed", "frustrated", "terrible",
       "awful", "disappointed", "worst", "problem", "issue", "wrong", "broken",
       "ugh", "stuck", "confused", "useless", "again", "still"}
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def analyze(text: str) -> Dict:
    raw = text or ""
    words = re.findall(r"[a-zA-Z']+", raw.lower())
    n = len(words)
    wset = set(words)
    formal = len(wset & FORMAL); casual = len(wset & CASUAL)
    pos = sum(w in POS for w in words); neg = sum(w in NEG for w in words)
    excl = raw.count("!"); caps = sum(1 for w in re.findall(r"[A-Za-z]+", raw) if w.isupper() and len(w) > 1)
    emoji = len(_EMOJI.findall(raw))

    mood = (pos - neg) / math.sqrt(max(n, 1))
    mood = max(-1.0, min(1.0, mood))
    intensity = excl + caps + emoji

    tags: List[str] = []
    tags.append("style:terse" if n < 8 else ("style:verbose" if n > 30 else "style:medium"))
    if formal > casual: tags.append("style:formal")
    elif casual > formal: tags.append("style:casual")
    if intensity >= 3: tags.append("style:high_energy")
    if neg >= 2 and pos == 0: tags.append("style:frustrated")
    # language flag: only ACTUAL non-Latin letter scripts (CJK/Hangul/Cyrillic/
    # Hebrew/Arabic) -- NOT smart quotes, em-dashes, or accented Latin.
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af"
                 r"\u0400-\u04ff\u0590-\u05ff\u0600-\u06ff]", raw):
        tags.append("style:non_english")
    return {"style_tags": tags, "mood": round(mood, 3), "intensity": intensity, "n_words": n}


def guidance(mood_ema: float, trend: float, style_tags: List[str]) -> str:
    parts = []
    if mood_ema <= -0.3: parts.append("user seems frustrated — lead with empathy and a fix")
    elif mood_ema >= 0.3: parts.append("user is upbeat — keep it warm")
    else: parts.append("neutral mood — stay clear and helpful")
    if trend <= -0.25: parts.append("mood is sliding vs. before — slow down, acknowledge it")
    if "style:terse" in style_tags: parts.append("match their brevity")
    if "style:verbose" in style_tags: parts.append("they like detail")
    if "style:formal" in style_tags: parts.append("keep tone formal")
    if "style:casual" in style_tags: parts.append("casual tone is fine")
    return "; ".join(parts)

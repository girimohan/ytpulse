"""Gazetteer-based entity linking tuned for code-mixed English/Hindi/Nepali chat.

Why a gazetteer and not a generic NER model: chat is short, romanized, code-mixed and full of
transliteration variants. A curated alias list (editable YAML) is more precise for the names
you actually care about, and `discover_candidates` surfaces new names to add.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .text import DEVA, WORD

# Suffixes glued onto names: Nepali/Hindi postpositions (Devanagari) and romanized forms.
_DEVA_SUFFIX = r"(?:ले|को|का|की|लाई|मा|बाट|सँग|संग|हरू|हरु|जी|जि|ने|से|में|का)?"
_LATIN_SUFFIX = r"(?:ji|jee|le|ko|lai|ka|ki|ne|ma|sir|da)?"
_BEFORE = rf"(?<![{WORD}])"
_AFTER = rf"(?![{WORD}])"


@dataclass(frozen=True)
class EntityHit:
    id: str
    start: int
    end: int


class EntityMatcher:
    def __init__(self, entities: list[dict]):
        self.registry = {e["id"]: {"name": e["name"], "type": e["type"], "aliases": e["aliases"]}
                         for e in entities}
        self._patterns: list[tuple[str, re.Pattern]] = []
        for e in entities:
            deva = [a for a in e["aliases"] if re.search(rf"[{DEVA}]", a)]
            latin = [a for a in e["aliases"] if a not in deva]
            parts = []
            for group, suffix in ((deva, _DEVA_SUFFIX), (latin, _LATIN_SUFFIX)):
                if not group:
                    continue
                alts = "|".join(self._alias_regex(a) for a in sorted(group, key=len, reverse=True))
                # emoji-only aliases (flags) have no word boundary concerns
                parts.append(rf"(?:{alts}){suffix}")
            pattern = _BEFORE + "(?:" + "|".join(parts) + ")" + _AFTER
            self._patterns.append((e["id"], re.compile(pattern, re.IGNORECASE)))
        self.alias_tokens = {t for e in entities for a in e["aliases"] for t in re.findall(rf"[{WORD}]+", a.lower())}

    @staticmethod
    def _alias_regex(alias: str) -> str:
        return r"\s+".join(re.escape(p) for p in alias.lower().split())

    def find(self, text: str) -> list[EntityHit]:
        """All entity hits in `text` (lowercased matching), one per (entity, span)."""
        low = text.lower()
        hits = []
        for eid, pat in self._patterns:
            for m in pat.finditer(low):
                hits.append(EntityHit(eid, m.start(), m.end()))
        return sorted(hits, key=lambda h: h.start)

    def name(self, eid: str) -> str:
        return self.registry[eid]["name"]

    def type(self, eid: str) -> str:
        return self.registry[eid]["type"]


def discover_candidates(texts: list[str], known_tokens: set[str], stop: set[str],
                        min_count: int = 3, top_n: int = 15) -> list[tuple[str, int]]:
    """Capitalised Latin words that are rarely seen in lowercase: likely names not in the gazetteer."""
    cap: dict[str, int] = {}
    low: dict[str, int] = {}
    for t in texts:
        for w in re.findall(r"\b[A-Za-z][a-z]{2,}\b", t):
            lw = w.lower()
            if w[0].isupper():
                cap[lw] = cap.get(lw, 0) + 1
            else:
                low[lw] = low.get(lw, 0) + 1
    out = [(w.title(), c) for w, c in cap.items()
           if c >= min_count and w not in known_tokens and w not in stop and low.get(w, 0) <= 0.2 * c]
    return sorted(out, key=lambda x: -x[1])[:top_n]

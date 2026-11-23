"""Text normalisation, tokenisation, emoji/hashtag extraction, language guess, spam rules."""
from __future__ import annotations

import re
import unicodedata

# Devanagari block minus the danda punctuation (U+0964, U+0965)
DEVA = "ऀ-ॣ०-ॿ"
WORD = rf"\w{DEVA}"

_ZERO_WIDTH = re.compile("[​‎‏⁠﻿]")
_REPEAT = re.compile(r"(.)\1{2,}")
_WS = re.compile(r"\s+")
URL_RE = re.compile(
    r"(https?://\S+|www\.\S+|\b[\w-]+\.(?:com|in|np|co|me|ly|tv|xyz|net|org|info)(?:/\S*)?\b|\bt\.me/\S+|\bwa\.me/\S+)",
    re.I,
)
SHORTCODE_RE = re.compile(r":([a-z0-9][a-z0-9_\-]*):", re.I)  # YouTube custom emoji ":folded-hands:"
HASHTAG_RE = re.compile(rf"#[{WORD}]+")
EMOJI_RE = re.compile(
    "[\U0001F1E6-\U0001F1FF]{2}"
    "|[\U0001F300-\U0001FAFF☀-➿⭐❤⬆✅❌](?:️)?"
)
TOKEN_RE = re.compile(rf"[{WORD}]+(?:['-][{WORD}]+)*")

PROMO_RE = re.compile(
    r"(sub\s*4\s*sub|subscribe to my|check (out )?my (channel|profile)|follow me|free (followers|crypto|robux)|"
    r"earn\s+\$?\d+|whats?app me|telegram|dm me|giveaway|crypto signals|investment plan)",
    re.I,
)

ROMAN_MARKERS = {
    "hai", "hain", "nahi", "nahin", "kya", "kyun", "kyu", "bhai", "acha", "accha", "achha", "bahut", "bohot",
    "hoga", "hua", "tha", "thi", "ke", "ki", "mein", "yeh", "woh", "kuch", "abhi", "namaste", "bakwas", "bilkul",
    "sahi", "chahiye", "karo", "kiya", "raha", "rahe", "mat", "tum", "aap", "hum", "mera", "apna", "desh",
    "sarkar", "ji", "jai", "aur", "lekin", "magar", "toh", "bhi", "dhanyawad", "shukriya", "badhiya", "zabardast",
    "kamaal", "chha", "chhan", "hoina", "haina", "ramro", "naramro", "dherai", "tapai", "tapaiko", "hami",
    "bhayo", "garnu", "garyo", "lagyo", "daju", "didi", "kitne", "baje", "kam", "ne", "ko",
}
NE_DEVA = {"छ", "छन्", "हुन्", "थियो", "गर्नु", "गरेको", "गर्ने", "तपाईं", "तपाई", "हामी", "हाम्रो", "मलाई", "तिमी",
           "भयो", "भएको", "छैन", "पनि", "र", "लाई", "ले", "बाट", "सँग", "धेरै", "राम्रो", "कहिले", "यो", "गरेन", "लाग्यो"}
HI_DEVA = {"है", "हैं", "था", "थी", "नहीं", "का", "की", "के", "में", "से", "पर", "और", "यह", "वह", "क्या",
           "कुछ", "बहुत", "अच्छा", "हम", "आप", "तुम", "मैं", "लेकिन", "भी", "तो", "सब", "कोई", "नतीजा", "ने"}


def normalize(text: str) -> str:
    """NFKC, strip zero-width chars, cap letter repeats at 2 ('soooo'->'soo'), squeeze spaces."""
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZERO_WIDTH.sub("", t).replace("’", "'")
    t = _REPEAT.sub(lambda m: m.group(1) * 2, t)
    return _WS.sub(" ", t).strip()


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def emojis(text: str) -> list[str]:
    found = EMOJI_RE.findall(text)
    found += [f":{m}:" for m in SHORTCODE_RE.findall(text)]
    return found


def hashtags(text: str) -> list[str]:
    return [h.lower() for h in HASHTAG_RE.findall(text)]


def letters_only(text: str) -> str:
    return "".join(c for c in text if c.isalpha())


def detect_lang(clean: str) -> str:
    """en | rom (romanized Hindi/Nepali) | hi | ne | mixed | emoji | other."""
    letters = [c for c in clean if c.isalpha()]
    if not letters:
        return "emoji" if emojis(clean) else "other"
    deva = sum("ऀ" <= c <= "ॿ" for c in letters) / len(letters)
    latin = sum(c.isascii() for c in letters) / len(letters)
    toks = set(tokens(clean))
    if deva >= 0.6:
        ne, hi = len(toks & NE_DEVA), len(toks & HI_DEVA)
        return "ne" if ne > hi else "hi"
    if latin >= 0.6:
        return "rom" if toks & ROMAN_MARKERS else "en"
    return "mixed"


def message_key(clean: str, emoji_list: list[str]) -> str:
    """Canonical form for duplicate / copy-paste detection."""
    k = re.sub(rf"[^{WORD}]+", "", clean.lower())
    return k or "".join(emoji_list)


def spam_flags(raw: str, clean: str, emoji_list: list[str], max_len: int) -> list[str]:
    flags = []
    if not clean:
        flags.append("empty")
    if URL_RE.search(raw):
        flags.append("url")
    if PROMO_RE.search(raw):
        flags.append("promo")
    if len(clean) > max_len:
        flags.append("too_long")
    if len(emoji_list) >= 15:
        flags.append("emoji_flood")
    words = tokens(clean)
    if len(words) >= 6 and len(set(words)) <= max(1, len(words) // 6):
        flags.append("word_flood")
    return flags


HARD_SPAM = {"url", "promo", "too_long", "emoji_flood", "word_flood"}

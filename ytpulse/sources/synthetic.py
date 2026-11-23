"""Synthetic chat generator for demos and tests.

Everything produced here is FAKE and carries source="synthetic"; reports built from it are
watermarked DEMO DATA. Never publish numbers derived from it as if they were real.
Mix: English, romanized Hindi/Nepali, Devanagari Hindi/Nepali, emoji, spam, a copy-paste
campaign, one flooding account and a few super chats.
"""
from __future__ import annotations

import random
import threading
from datetime import datetime, timedelta, timezone
from typing import Iterator

from ..models import ChatMessage, to_utc_iso

PERSONS = ["Modi", "Modi ji", "Balen", "Balen Shah", "मोदी जी", "बालेन", "Balendra", "Namo"]
POS = [
    "{E} is doing a great job 👏", "Proud of {E}, what a leader!", "{E} zindabad 🔥",
    "Bahut accha hua, {E} ne kamaal kar diya", "{E} जी ने बहुत अच्छा काम किया 🙏",
    "{E} को स्वागत छ, धेरै राम्रो भयो", "Excellent speech by {E}, very strong ❤️",
    "Historic visit, good for India Nepal friendship ❤️", "Great relations, hope trade grows 🇮🇳🇳🇵",
    "Jai Hind! Jai Nepal! 🙏", "{E} ramro bolyo, dherai ramro", "Respect for {E}, truly inspiring",
    "भारत नेपाल मित्रता जिंदाबाद 🙏", "Wonderful welcome, beautiful ceremony 😍",
]
NEG = [
    "{E} is a failure, total drama", "Nothing will change, only photo ops 🙄",
    "{E} ne kuch nahi kiya, bakwas", "Shame on {E}, sell out", "Kalapani pe baat kyun nahi hui? shameful",
    "{E} हटाओ, सब झूठ है", "{E} ले केही गरेन, लाज लाग्यो", "Fake smiles, no real outcome 👎",
    "Border issue ignored again, very disappointing", "{E} is a liar, waste of time 😡",
    "सब बकवास है, कोई नतीजा नहीं", "Useless meeting, corruption everywhere", "{E} ko kam naramro chha",
    "Total joke, pathetic 🤮",
]
NEU = [
    "What time is the press conference?", "Which channel is this?", "{E} just arrived",
    "Live from Delhi", "Who is sitting next to {E}?", "kitne baje start hoga?",
    "यो कहिले सुरु हुन्छ?", "Hello from Mumbai", "Hello from Kathmandu", "Audio is low",
    "Is there Nepali translation?", "Subtitles please", "Where is Jaishankar sitting?",
]
MIXED = [
    "Welcome {E1} but what about Kalapani? {E2} must raise it",
    "{E1} was great today, {E2} was a disappointment",
    "{E1} accha tha lekin {E2} ne kuch nahi bola",
]
CAMPAIGN = "Balen zindabad 🔥🔥 support Balen for Nepal #BalenForNepal"
PROMO = [
    "subscribe to my channel for free crypto signals https://t.me/fakepump",
    "EARN $500 DAILY from home, whatsapp me wa.me/000000",
    "sub4sub check my channel www.example.xyz",
]
EMOJI_ONLY = ["🔥🔥🔥", "🙏🙏", "❤️❤️❤️", "👏👏👏", "🇮🇳🇳🇵", "😡😡", "👎"]


def generate(n: int = 1500, seed: int = 7, video_id: str = "DEMO0000000",
             start: datetime | None = None, minutes: int = 45) -> list[tuple[ChatMessage, str]]:
    """Return (message, intended_label) pairs. Labels are for testing only."""
    rng = random.Random(seed)
    start = start or datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
    out: list[tuple[ChatMessage, str]] = []
    authors = [f"UC{rng.getrandbits(48):012x}" for _ in range(max(60, n // 6))]

    def when() -> datetime:
        # volume spikes around minutes 12 and 30 (handshake / joint statement)
        m = rng.choice([rng.uniform(0, minutes), rng.gauss(12, 2), rng.gauss(30, 3)])
        m = min(max(m, 0), minutes - 0.01)
        return start + timedelta(minutes=m)

    def add(text: str, label: str, author: str | None = None, ts: datetime | None = None,
            kind: str = "text", amount: str | None = None) -> None:
        i = len(out)
        out.append((ChatMessage(
            id=f"syn-{seed}-{i:06d}", video_id=video_id, source="synthetic",
            ts=to_utc_iso(ts or when()), author_id=author or rng.choice(authors),
            text=text, kind=kind, amount=amount), label))

    organic = int(n * 0.80)
    for _ in range(organic):
        r = rng.random()
        if r < 0.10:
            add(rng.choice(MIXED).format(E1=rng.choice(PERSONS[:4]), E2=rng.choice(PERSONS[4:])), "neutral")
        elif r < 0.42:
            add(rng.choice(POS).format(E=rng.choice(PERSONS)), "positive")
        elif r < 0.62:
            add(rng.choice(NEG).format(E=rng.choice(PERSONS)), "negative")
        elif r < 0.92:
            add(rng.choice(NEU).format(E=rng.choice(PERSONS)), "neutral")
        else:
            e = rng.choice(EMOJI_ONLY)
            add(e, "negative" if e in ("😡😡", "👎") else "positive")
    # coordinated copy-paste campaign from many accounts
    burst_start = start + timedelta(minutes=20)
    for a in rng.sample(authors, min(28, len(authors))):
        add(CAMPAIGN, "positive", author=a, ts=burst_start + timedelta(seconds=rng.uniform(0, 90)))
    # promo spam
    for _ in range(int(n * 0.03)):
        add(rng.choice(PROMO), "neutral")
    # one flooding account
    flood_author, t0 = "UCflooder0000", when()
    for k in range(40):
        add("BALEN BALEN BALEN BALEN", "positive", author=flood_author, ts=t0 + timedelta(seconds=k))
    # a few super chats
    for amt, txt in [("₹500.00", "Great discussion, thank you!"), ("NPR 1,000", "Please discuss the border issue"),
                     ("₹100.00", "")]:
        add(txt, "neutral", kind="superchat", amount=amt)
    out.sort(key=lambda p: p[0].ts)
    return out


class SyntheticSource:
    def __init__(self, n: int = 1500, seed: int = 7, video_id: str = "DEMO0000000", batch: int = 200):
        self.pairs = generate(n, seed, video_id)
        self.batch = batch

    def batches(self, stop: threading.Event) -> Iterator[list[ChatMessage]]:
        msgs = [m for m, _ in self.pairs]
        for i in range(0, len(msgs), self.batch):
            if stop.is_set():
                return
            yield msgs[i:i + self.batch]

"""Sentiment backends. Every backend maps a list of texts to scores in [-1, 1].

  lexicon      zero-dependency baseline: English + romanized Hindi/Nepali + Devanagari + emoji,
               with negation and intensifier handling. Fast, transparent, weaker on sarcasm.
  transformer  multilingual XLM-R model (needs `pip install -e .[ml]`, downloads weights once).
  hybrid       transformer score blended with the lexicon when the lexicon fires; this is the
               recommended mode for romanized Hinglish where the transformer is weakest.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Protocol

from . import text as T

log = logging.getLogger("ytpulse.sentiment")

POS_WORDS = """
good great excellent amazing awesome proud best love loved lovely nice beautiful historic brilliant wonderful
happy hope strong friend friendship respect welcome congratulations thanks thank bravo legend legendary win
victory powerful smart genius superb fantastic positive progress growth peace cooperation support supportive
blessed hero inspiring honest wow inspiring impressive classy gem
jai zindabad accha acha achha badhiya badiya shandar zabardast kamaal mast sahi sundar dhanyawad shukriya
pyar garv gaurav jabardast ramro raamro badhai shubhkamana dhanyabad salam
अच्छा अच्छी बढ़िया शानदार जबरदस्त कमाल बधाई धन्यवाद शुक्रिया गर्व सुंदर महान जिंदाबाद ज़िंदाबाद जय स्वागत
राम्रो राम्रा शुभकामना गौरव सुन्दर महान् बधाई
मजा मज्जा मजाको दमदार दम्दार गज्जब राम्रै सलुट स्यालुट सेल्युट जिन्दावाद
mazza maja majja mitho ramrai gajjab gajab damdar damdaar salute salut
folded-hands red-heart fire thumbs-up clapping-hands smiling-face-with-heart-eyes
""".split()
NEG_WORDS = """
bad worst terrible awful failure fail failed fake shame shameful disgusting hate hated useless corrupt
corruption liar lie lies joke drama nonsense stupid idiot traitor betrayal disappointing disappointed
pathetic waste sellout disappoint disappointment shameless betray betrayed cheat cheater fraud trash garbage angry worried threat danger propaganda
bakwas bekar bekaar jhooth jhuth faltu ghatiya kharab bura buri sharm sharmnak dhokha chor gaddar nikamma
nakli dhong dramebaaz galat lanat afsos naramro jhuto dhoka lajja lajjajanak
बकवास बेकार झूठ झूठा झूठे घटिया खराब बुरा शर्म शर्मनाक धोखा चोर गद्दार नकली ढोंग गलत लाज नराम्रो
झुटो धोका फालतू लाजमर्दो
thumbs-down pouting-face face-with-rolling-eyes face-vomiting
""".split()
EMOJI_POS = set("👏🔥❤🙏😍💪👍🎉🥰😊🙌✨💯😁😀🤝🫡")
EMOJI_NEG = set("👎😡🤬😠🙄😤🤮💩😒😞😢🤡")
EMOJI_FLAG = set()  # flags are patriotic cheering; handled as mild positive below
PHRASES = {  # multiword cues, matched on the lowercased clean string
    "nothing will change": -1.5, "no result": -1.2, "waste of time": -1.8, "sell out": -1.5,
    "photo op": -1.0, "photo ops": -1.0, "not good": -1.5, "well done": 1.5, "thank you": 1.2,
    "kuch nahi kiya": -1.5, "kuch nahi": -0.8, "bahut accha": 2.0, "jai hind": 0.6, "jai nepal": 0.6,
    "जय हिंद": 0.6, "जय नेपाल": 0.6, "कोई नतीजा नहीं": -1.5, "सब झूठ": -1.5,
}
NEGATORS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "cant", "can't", "wont", "won't",
            "nahi", "nahin", "na", "mat", "nai", "hoina", "haina", "नहीं", "न", "छैन", "होइन", "नै", "kabhi"}
BOOST = {"very", "really", "so", "too", "extremely", "super", "totally", "bahut", "bohot", "bhot", "kaafi",
         "dherai", "ekdum", "bilkul", "बहुत", "बिल्कुल", "धेरै", "एकदम"}
DAMP = {"slightly", "somewhat", "thoda", "kinda", "थोड़ा", "अलिकति"}

BASE = 1.5
ALPHA = 6.0  # VADER-style squashing constant: s / sqrt(s^2 + ALPHA)


class SentimentModel(Protocol):
    name: str

    def predict(self, texts: list[str]) -> list[float]: ...


def _squash(s: float) -> float:
    return s / math.sqrt(s * s + ALPHA)


class LexiconModel:
    name = "lexicon-v1"

    def __init__(self):
        self.lex: dict[str, float] = {w: BASE for w in POS_WORDS}
        self.lex.update({w: -BASE for w in NEG_WORDS})

    def _lookup(self, tok: str) -> float:
        if tok in self.lex:
            return self.lex[tok]
        reduced = re.sub(r"(.)\1+", r"\1", tok)  # 'greaaat' -> 'great'
        if reduced in self.lex:
            return self.lex[reduced]
        for suf in ("s", "ly", "ness", "ment", "ed", "ing"):  # cheap stemming: 'liars', 'shamelessly'
            if tok.endswith(suf) and len(tok) - len(suf) >= 4 and tok[: -len(suf)] in self.lex:
                return self.lex[tok[: -len(suf)]]
        return 0.0

    def score_with_hits(self, text: str) -> tuple[float, int]:
        low = text.lower()
        toks = T.tokens(low)
        total, hits = 0.0, 0
        for i, tok in enumerate(toks):
            v = self._lookup(tok)
            if not v:
                continue
            hits += 1
            before = toks[max(0, i - 3):i]
            after = toks[i + 1:i + 3]
            if any(t in BOOST for t in before[-1:]):
                v *= 1.5
            if any(t in DAMP for t in before[-1:]):
                v *= 0.6
            if any(t in NEGATORS for t in before) or any(t in NEGATORS for t in after):
                v *= -0.7
            total += v
        for phrase, w in PHRASES.items():
            if phrase in low:
                total += w
                hits += 1
        for e in T.EMOJI_RE.findall(text):
            e = e.rstrip("️")
            if e in EMOJI_POS:
                total += 1.0
                hits += 1
            elif e in EMOJI_NEG:
                total -= 1.0
                hits += 1
            elif len(e) == 2:  # flag emoji
                total += 0.3
                hits += 1
        for code in T.SHORTCODE_RE.findall(text):
            v = self._lookup(code.lower())
            if v:
                total += v
                hits += 1
        return _squash(total), hits

    def predict(self, texts: list[str]) -> list[float]:
        return [self.score_with_hits(t)[0] for t in texts]


class TransformerModel:
    def __init__(self, model: str = "cardiffnlp/twitter-xlm-roberta-base-sentiment",
                 batch_size: int = 32, device: int | None = None):
        try:
            from transformers import pipeline
            import torch
        except ImportError as e:  # pragma: no cover
            raise SystemExit("Transformer backend needs: pip install -e .[ml]") from e
        if device is None:
            device = 0 if torch.cuda.is_available() else -1
        log.info("loading %s on %s", model, "cuda" if device >= 0 else "cpu")
        self.pipe = pipeline("text-classification", model=model, top_k=None, truncation=True,
                             max_length=128, device=device)
        self.name = model
        self.batch_size = batch_size

    @staticmethod
    def _score(label_scores: list[dict]) -> float:
        p = {d["label"].lower(): d["score"] for d in label_scores}
        pos = p.get("positive", p.get("label_2", 0.0))
        neg = p.get("negative", p.get("label_0", 0.0))
        return float(pos - neg)

    def predict(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        out = self.pipe(texts, batch_size=self.batch_size)
        return [self._score(o) for o in out]


class HybridModel:
    def __init__(self, transformer: TransformerModel, lexicon: LexiconModel, weight: float = 0.65):
        self.tr, self.lex, self.w = transformer, lexicon, weight
        self.name = f"hybrid({transformer.name}+{lexicon.name})"

    def predict(self, texts: list[str]) -> list[float]:
        tr = self.tr.predict(texts)
        out = []
        for t, s in zip(texts, tr):
            ls, hits = self.lex.score_with_hits(t)
            out.append(s if hits == 0 else self.w * s + (1 - self.w) * ls)
        return out


def build_model(cfg: dict) -> SentimentModel:
    backend = cfg.get("backend", "lexicon")
    lex = LexiconModel()
    if backend == "lexicon":
        return lex
    tr = TransformerModel(cfg.get("model", "cardiffnlp/twitter-xlm-roberta-base-sentiment"),
                          cfg.get("batch_size", 32))
    if backend == "transformer":
        return tr
    if backend == "hybrid":
        return HybridModel(tr, lex, cfg.get("hybrid_model_weight", 0.65))
    raise ValueError(f"Unknown sentiment backend: {backend}")


def to_label(score: float, pos: float = 0.2, neg: float = -0.2) -> str:
    return "positive" if score >= pos else "negative" if score <= neg else "neutral"

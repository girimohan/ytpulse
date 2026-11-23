import pytest

from ytpulse import config
from ytpulse.nlp import text as T
from ytpulse.nlp.entities import EntityMatcher
from ytpulse.nlp.sentiment import LexiconModel, to_label
from ytpulse.sources import extract_video_id
from ytpulse.sources.synthetic import generate


@pytest.fixture(scope="module")
def matcher():
    return EntityMatcher(config.load_entities())


def ids(m, text):
    return {h.id for h in m.find(T.normalize(text))}


@pytest.mark.parametrize("text,expected", [
    ("Modi ji is here", {"modi"}),
    ("modiji zindabad", {"modi"}),
    ("मोदीजी ने कहा", {"modi"}),
    ("बालेनले राम्रो भाषण दिए", {"balen"}),          # Nepali suffix attached
    ("Balen's speech was good", {"balen"}),
    ("Balen and Modi together 🇮🇳🇳🇵", {"balen", "modi", "india", "nepal"}),
    ("Oliver Twist is a book", set()),                # 'oli' must not match inside a word
    ("kalapani pe baat karo", {"border"}),
    ("नेपालमा बिजुली", {"nepal", "energy"}),
    ("nothing here", set()),
])
def test_entity_matching(matcher, text, expected):
    assert ids(matcher, text) == expected


def test_entity_hit_is_longest_alias(matcher):
    assert len([h for h in matcher.find("narendra modi")]) == 1


@pytest.mark.parametrize("text,lang", [
    ("This is a great speech", "en"),
    ("bahut accha bola yaar", "rom"),
    ("यह बहुत अच्छा है", "hi"),
    ("यो धेरै राम्रो छ", "ne"),
    ("🔥🔥🔥", "emoji"),
])
def test_language(text, lang):
    assert T.detect_lang(T.normalize(text)) == lang


def test_normalize_caps_repeats_and_zero_width():
    assert T.normalize("soooooo​  good!!!!") == "soo good!!"


def test_spam_flags():
    f = lambda s: T.spam_flags(s, T.normalize(s), T.emojis(s), 500)
    assert "url" in f("see https://spam.example/x")
    assert "promo" in f("sub4sub please")
    assert "emoji_flood" in f("🔥" * 20)
    assert "word_flood" in f("balen " * 10)
    assert f("Balen is great 🔥") == []


@pytest.mark.parametrize("text,label", [
    ("This is excellent, proud of him", "positive"),
    ("not good at all", "negative"),
    ("bakwas hai ye sab, shame", "negative"),
    ("बहुत अच्छा काम किया 🙏", "positive"),
    ("तिमीले केही गरेन, लाज लाग्यो", "negative"),
    ("What time does it start?", "neutral"),
    ("greaaat speech", "positive"),
    ("👎", "negative"),
])
def test_lexicon_polarity(text, label):
    m = LexiconModel()
    assert to_label(m.predict([T.normalize(text)])[0]) == label


def test_lexicon_accuracy_on_synthetic_is_reasonable():
    """Sanity floor, not a benchmark: templates are easy and written by the same author as the lexicon."""
    pairs = generate(600, seed=3)
    m = LexiconModel()
    pred = [to_label(s) for s in m.predict([T.normalize(msg.text) for msg, _ in pairs])]
    acc = sum(p == l for p, (_, l) in zip(pred, pairs)) / len(pairs)
    assert acc > 0.75, acc


@pytest.mark.parametrize("v", [
    "https://www.youtube.com/watch?v=ZjQ7P_cbzYQ", "https://youtu.be/ZjQ7P_cbzYQ?t=5",
    "https://www.youtube.com/live/ZjQ7P_cbzYQ", "ZjQ7P_cbzYQ"])
def test_extract_video_id(v):
    assert extract_video_id(v) == "ZjQ7P_cbzYQ"

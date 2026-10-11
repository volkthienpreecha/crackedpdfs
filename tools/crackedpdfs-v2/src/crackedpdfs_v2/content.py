"""Instruction and benign text pools, content folds, and exact length matching.

Every PDF in a v2 item carries one of two texts: the injected instruction (a
payload from ``tools/crackedpdfs-payloads``) or a benign text of the same
character length. The benign text is real document prose taken from GovDocs1
files that are never used as base documents or as real negatives, so neither
role can be told apart by a generator phrase or by length.

Both pools are dealt into content folds. A payload cluster and a benign source
document each belong to exactly one fold, so holding out a fold removes every
paraphrase of a payload and every sentence of a benign source at once.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

MESSAGE_TYPES: tuple[str, ...] = (
    "instruction_override",
    "policy_framing",
    "task_hijack",
    "system_extraction",
    "refusal_suppression",
    "data_exfiltration",
    "agent_tool_manipulation",
    "summarization_steering",
)

# Payloads must survive WinAnsi encoding (the primary injector writes a
# standard 14 Helvetica font) and fit on one page at body size.
PAYLOAD_MIN_CHARS = 60
PAYLOAD_MAX_CHARS = 420

SENTENCE_MIN_CHARS = 25
SENTENCE_MAX_CHARS = 320

_WS_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_IMPERATIVE_RE = re.compile(
    r"^(please|do not|don't|never|always|submit|return|send|complete|attach|include|contact|call|"
    r"click|visit|refer|see|note|read|sign|mail|fax|enter|list|provide|use|keep|report|review|"
    r"ensure|make sure|check|select|indicate|print|type|bring|follow|write|answer|describe|explain|"
    r"identify|retain|notify|forward|remove|allow|apply|file|record|verify)\b",
    re.IGNORECASE,
)
_SECOND_PERSON_RE = re.compile(r"\b(you|your|yours|yourself)\b", re.IGNORECASE)
_FIRST_PERSON_RE = re.compile(r"\b(I|me|my|mine|myself)\b")
_HYPHEN_BREAK_RE = re.compile(r"[a-z]- [a-z]")
_STOPWORDS = frozenset(
    {"the", "of", "and", "to", "in", "is", "for", "that", "with", "on", "be", "are", "by", "this", "as"}
    | {"was", "were", "it", "or", "an", "at", "from", "which", "will", "not", "have", "has"}
)
_SMART_PUNCTUATION = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalize(text: str) -> str:
    """NFKC, ASCII punctuation, collapsed whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_SMART_PUNCTUATION)
    return _WS_RE.sub(" ", text).strip()


def winansi_safe(text: str) -> bool:
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return all(ch.isprintable() for ch in text)


def stable_fold(key: str, folds: int, salt: str) -> int:
    digest = hashlib.sha256(f"{salt}|{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % folds


@dataclass(frozen=True)
class Style:
    """Surface traits a text-only classifier could use to tell the roles apart."""

    second_person: bool
    first_person: bool
    terminal: str  # ".", "!", "?", or "" when the text ends without one


def text_style(text: str) -> Style:
    return Style(
        second_person=bool(_SECOND_PERSON_RE.search(text)),
        first_person=bool(_FIRST_PERSON_RE.search(text)),
        terminal=text[-1] if text and text[-1] in ".!?" else "",
    )


@dataclass(frozen=True)
class Payload:
    payload_id: str
    text: str
    message_type: str
    cluster_id: str
    source: str
    license: str
    content_fold: int


@dataclass(frozen=True)
class BenignSentence:
    sentence_id: str
    text: str
    source_doc: str
    imperative: bool
    content_fold: int
    second_person: bool = False
    first_person: bool = False


def load_payloads(path: str | Path, folds: int, seed: int) -> list[Payload]:
    """Typed English payloads that the injector can encode, with clusters dealt into folds.

    Clusters are dealt within each message type by size, so every fold holds a
    near-equal number of rows of every type and no cluster spans two folds.
    """
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("language") != "en" or row.get("message_type") not in MESSAGE_TYPES:
                continue
            text = normalize(row["text"])
            if not (PAYLOAD_MIN_CHARS <= len(text) <= PAYLOAD_MAX_CHARS) or not winansi_safe(text):
                continue
            rows.append({**row, "text": text})

    # A cluster can mix message types; it is dealt with the type that holds
    # most of its rows (ties broken by name), so the stratum reflects its bulk.
    type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        type_counts[row["cluster_id"]][row["message_type"]] += 1
    clusters_by_type: dict[str, list[str]] = defaultdict(list)
    for cluster, counts in sorted(type_counts.items()):
        majority = min(counts, key=lambda message_type: (-counts[message_type], message_type))
        clusters_by_type[majority].append(cluster)

    # Within each type, clusters go largest first to the fold holding the
    # fewest rows of that type, so one big paraphrase cluster cannot skew a
    # fold. The seeded shuffle only breaks ties between equal-sized clusters.
    rng = random.Random(seed)
    fold_of_cluster: dict[str, int] = {}
    for message_type in MESSAGE_TYPES:
        clusters = sorted(clusters_by_type.get(message_type, []))
        rng.shuffle(clusters)
        clusters.sort(key=lambda cluster: -sum(type_counts[cluster].values()))
        load = [0] * folds
        for cluster in clusters:
            fold = min(range(folds), key=lambda k: (load[k], k))
            fold_of_cluster[cluster] = fold
            load[fold] += sum(type_counts[cluster].values())

    return [
        Payload(
            payload_id=row["id"],
            text=row["text"],
            message_type=row["message_type"],
            cluster_id=row["cluster_id"],
            source=row["source"],
            license=str(row["license"]).lower(),
            content_fold=fold_of_cluster[row["cluster_id"]],
        )
        for row in sorted(rows, key=lambda r: r["id"])
    ]


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.split(normalize(text)) if part.strip()]


def is_prose_sentence(sentence: str) -> bool:
    """Reject tables, headers, numbers, and extraction debris."""
    if not (SENTENCE_MIN_CHARS <= len(sentence) <= SENTENCE_MAX_CHARS):
        return False
    if not winansi_safe(sentence) or sentence[-1] not in ".!?":
        return False
    words = sentence.split()
    if len(words) < 5 or sum(len(w) > 25 for w in words) > 0:
        return False
    letters = sum(ch.isalpha() for ch in sentence)
    if letters / len(sentence) < 0.7:
        return False
    if sum(ch.isupper() for ch in sentence) / max(letters, 1) > 0.3:
        return False
    if sum(len(w) == 1 and w.isalpha() and w not in {"a", "A", "I"} for w in words) > 2:
        return False
    # Line-break hyphenation ("ama- teur"), truncated sentences, and non-English
    # lines are extraction artifacts a detector could key on.
    if _HYPHEN_BREAK_RE.search(sentence) or sentence.endswith(".."):
        return False
    if sum(w.lower().strip(",;:") in _STOPWORDS for w in words) / len(words) < 0.12:
        return False
    return sentence[0].isupper() or sentence[0] in "\"'("


def benign_sentences_from_text(
    text: str, source_doc: str, folds: int, salt: str, limit: int | None = None
) -> list[BenignSentence]:
    fold = stable_fold(source_doc, folds, salt)
    seen: set[str] = set()
    out: list[BenignSentence] = []
    for sentence in split_sentences(text):
        if sentence in seen or not is_prose_sentence(sentence):
            continue
        seen.add(sentence)
        out.append(
            BenignSentence(
                sentence_id="bs-" + hashlib.sha256(f"{source_doc}|{sentence}".encode()).hexdigest()[:12],
                text=sentence,
                source_doc=source_doc,
                imperative=bool(_IMPERATIVE_RE.match(sentence)),
                content_fold=fold,
                second_person=bool(_SECOND_PERSON_RE.search(sentence)),
                first_person=bool(_FIRST_PERSON_RE.search(sentence)),
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def write_jsonl(rows: Iterable[object], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def read_benign_pool(path: str | Path) -> list[BenignSentence]:
    with open(path, encoding="utf-8") as handle:
        return [BenignSentence(**json.loads(line)) for line in handle]


class LengthMatcher:
    """Draws benign prose of an exact character length from one content fold.

    Sentences are joined with single spaces. The last sentence is chosen from
    an index by length, so the result is whole sentences that sum to the target
    exactly; when no exact fit exists the closest fit within ``tolerance``
    characters is returned.

    Without a ``style``, the text opens with an imperative sentence ("Please
    return the completed form...") with probability ``imperative_share``, so
    instruction mood alone does not identify the injected role. With the
    payload's ``style``, the draw also copies its surface traits: it opens with
    a sentence that addresses the reader or speaks in the first person when the
    payload does, ends with the same terminal punctuation where the pool allows
    it, and drops the final mark when the payload has none.

    Exact length comes first: a styled draw that misses the length gives way
    to an unstyled one that hits it. Trait-matched openers come from small
    sub-pools, so a sentence already used ``max_reuse`` times is never an
    opener again (the draw moves to the next opener rule), and closing
    sentences prefer the least used. Otherwise one short "you" sentence could
    recur in hundreds of items and become a memorisable benign marker.
    """

    def __init__(
        self,
        sentences: Sequence[BenignSentence],
        imperative_share: float = 0.5,
        tolerance: int = 3,
        max_reuse: int = 8,
    ):
        self.imperative_share = imperative_share
        self.tolerance = tolerance
        self.max_reuse = max_reuse
        self.usage: Counter[str] = Counter()
        self.by_fold: dict[int, list[BenignSentence]] = defaultdict(list)
        self.imperative_by_fold: dict[int, list[BenignSentence]] = defaultdict(list)
        self.lengths_by_fold: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for sentence in sentences:
            self.by_fold[sentence.content_fold].append(sentence)
            if sentence.imperative:
                self.imperative_by_fold[sentence.content_fold].append(sentence)
        for fold, items in self.by_fold.items():
            self.lengths_by_fold[fold] = sorted((len(s.text), i) for i, s in enumerate(items))
        self._trait_cache: dict[tuple[int, tuple[str, ...], str], tuple[list[int], list[BenignSentence]]] = {}

    def _closest(
        self, fold: int, length: int, rng: random.Random, used: set[str], terminal: str = ""
    ) -> BenignSentence | None:
        index = self.lengths_by_fold[fold]
        items = self.by_fold[fold]
        for slack in range(self.tolerance + 1):
            for candidate_length in {length - slack, length + slack}:
                lo = bisect_left(index, (candidate_length, -1))
                hi = bisect_left(index, (candidate_length + 1, -1))
                options = [items[i] for _, i in index[lo:hi] if items[i].sentence_id not in used]
                if terminal:
                    options = [s for s in options if s.text.endswith(terminal)] or options
                if options:
                    fresh = [s for s in options if self.usage[s.sentence_id] < self.max_reuse]
                    return rng.choice(fresh) if fresh else min(options, key=lambda s: self.usage[s.sentence_id])
        return None

    def _sample(
        self, lengths: list[int], options: list[BenignSentence], limit: int, rng: random.Random
    ) -> BenignSentence | None:
        """A random opener below the reuse cap that fills ``limit`` exactly or leaves room for a closer.

        Anything in between would leave a gap no sentence can fill.
        """
        room = options[: bisect_right(lengths, limit - SENTENCE_MIN_CHARS - 1)]
        exact = options[bisect_left(lengths, limit) : bisect_right(lengths, limit)]
        fresh = [s for s in (*room, *exact) if self.usage[s.sentence_id] < self.max_reuse]
        return rng.choice(fresh) if fresh else None

    def _trait_index(self, fold: int, flags: tuple[str, ...], terminal: str) -> tuple[list[int], list[BenignSentence]]:
        """Sentences in a fold carrying every trait in ``flags`` (and ``terminal``), sorted by length."""
        key = (fold, flags, terminal)
        if key not in self._trait_cache:
            options = sorted(
                (
                    s
                    for s in self.by_fold[fold]
                    if all(getattr(s, f) for f in flags) and (not terminal or s.text.endswith(terminal))
                ),
                key=lambda s: len(s.text),
            )
            self._trait_cache[key] = ([len(s.text) for s in options], options)
        return self._trait_cache[key]

    def _openers(self, fold: int, rng: random.Random, style: Style | None, budget: int) -> list[BenignSentence]:
        if style is not None and (style.second_person or style.first_person):
            wanted = tuple(flag for flag in ("second_person", "first_person") if getattr(style, flag))

            def pick(limit: int, flags: tuple[str, ...]) -> BenignSentence | None:
                # A short text may be the opener alone, so prefer the payload's
                # closing mark when it is "?" or "!".
                for terminal in dict.fromkeys((style.terminal if style.terminal in ("?", "!") else "", "")):
                    lengths, options = self._trait_index(fold, flags, terminal)
                    choice = self._sample(lengths, options, limit, rng)
                    if choice is not None:
                        return choice
                return None

            single = pick(budget, wanted)
            if single is not None:
                return [single]
            # One sentence per trait, sharing the budget; failing that, one trait.
            pair = [pick((budget - 1) // 2, (flag,)) for flag in wanted]  # each leaves room or fits
            if all(pair):
                return [s for s in pair if s is not None]
            for flag in wanted:
                fallback = pick(budget, (flag,))
                if fallback is not None:
                    return [fallback]
        if rng.random() < self.imperative_share:
            lengths, imperative = self._trait_index(fold, ("imperative",), "")
            choice = self._sample(lengths, imperative, budget, rng)
            if choice is not None:
                return [choice]
        return []

    def draw(
        self, length: int, fold: int, rng: random.Random, attempts: int = 200, style: Style | None = None
    ) -> tuple[str, list[str]]:
        try:
            text, ids = self._draw(length, fold, rng, attempts, style)
        except ValueError:
            if style is None:
                raise
            text, ids = self._draw(length, fold, rng, attempts, None)
        if style is not None and len(text) != length:
            plain = self._draw(length, fold, rng, attempts, None)
            if abs(len(plain[0]) - length) < abs(len(text) - length):
                text, ids = plain
        self.usage.update(ids)
        return text, ids

    def _draw(
        self, length: int, fold: int, rng: random.Random, attempts: int, style: Style | None
    ) -> tuple[str, list[str]]:
        if fold not in self.by_fold:
            raise ValueError(f"No benign sentences in content fold {fold}.")
        # A payload without closing punctuation gets a text one character
        # longer whose final mark is then dropped.
        strip_terminal = style is not None and style.terminal == ""
        target = length + strip_terminal
        terminal = style.terminal if style is not None else ""
        items = self.by_fold[fold]
        best: tuple[tuple[int, bool], str, list[str]] | None = None
        for _ in range(attempts):
            chosen: list[BenignSentence] = []
            used: set[str] = set()
            for opener in self._openers(fold, rng, style, target):
                chosen.append(opener)
                used.add(opener.sentence_id)
            while True:
                current = len(" ".join(s.text for s in chosen))
                remaining = target - current - (1 if chosen else 0)
                if remaining <= SENTENCE_MAX_CHARS:
                    break
                pick = rng.choice(items)
                if pick.sentence_id in used:
                    unused = [s for s in items if s.sentence_id not in used]
                    if not unused:
                        break
                    pick = rng.choice(unused)
                chosen.append(pick)
                used.add(pick.sentence_id)
            remaining = target - len(" ".join(s.text for s in chosen)) - (1 if chosen else 0)
            if remaining >= SENTENCE_MIN_CHARS:
                last = self._closest(fold, remaining, rng, used, terminal)
                if last is not None:
                    chosen.append(last)
            elif chosen and remaining < 0:
                continue
            text = " ".join(s.text for s in chosen)
            if strip_terminal and text:
                text = text[:-1]
            score = (abs(len(text) - length), bool(terminal) and not text.endswith(terminal))
            if best is None or score < best[0]:
                best = (score, text, [s.sentence_id for s in chosen])
            if score == (0, False):
                break
        if best is None or best[0][0] > self.tolerance:
            raise ValueError(f"No benign text within {self.tolerance} characters of length {length} in fold {fold}.")
        return best[1], best[2]

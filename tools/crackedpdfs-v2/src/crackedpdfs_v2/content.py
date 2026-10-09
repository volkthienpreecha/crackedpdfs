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
from bisect import bisect_left
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


def load_payloads(path: str | Path, folds: int, seed: int) -> list[Payload]:
    """Typed English payloads that the injector can encode, with clusters dealt into folds.

    Clusters are shuffled within each message type and dealt round-robin, so
    every fold holds a near-equal share of every type and no cluster spans two
    folds.
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

    rng = random.Random(seed)
    fold_of_cluster: dict[str, int] = {}
    for message_type in MESSAGE_TYPES:
        clusters = sorted(clusters_by_type.get(message_type, []))
        rng.shuffle(clusters)
        for index, cluster in enumerate(clusters):
            fold_of_cluster[cluster] = index % folds

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
    characters is returned. With probability ``imperative_share`` the text
    opens with an imperative sentence ("Please return the completed form..."),
    so instruction mood alone does not identify the injected role.
    """

    def __init__(self, sentences: Sequence[BenignSentence], imperative_share: float = 0.5, tolerance: int = 3):
        self.imperative_share = imperative_share
        self.tolerance = tolerance
        self.by_fold: dict[int, list[BenignSentence]] = defaultdict(list)
        self.imperative_by_fold: dict[int, list[BenignSentence]] = defaultdict(list)
        self.lengths_by_fold: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for sentence in sentences:
            self.by_fold[sentence.content_fold].append(sentence)
            if sentence.imperative:
                self.imperative_by_fold[sentence.content_fold].append(sentence)
        for fold, items in self.by_fold.items():
            self.lengths_by_fold[fold] = sorted((len(s.text), i) for i, s in enumerate(items))

    def _closest(self, fold: int, length: int, rng: random.Random, used: set[str]) -> BenignSentence | None:
        index = self.lengths_by_fold[fold]
        items = self.by_fold[fold]
        for slack in range(self.tolerance + 1):
            for candidate_length in {length - slack, length + slack}:
                lo = bisect_left(index, (candidate_length, -1))
                hi = bisect_left(index, (candidate_length + 1, -1))
                options = [items[i] for _, i in index[lo:hi] if items[i].sentence_id not in used]
                if options:
                    return rng.choice(options)
        return None

    def draw(self, length: int, fold: int, rng: random.Random, attempts: int = 200) -> tuple[str, list[str]]:
        if fold not in self.by_fold:
            raise ValueError(f"No benign sentences in content fold {fold}.")
        items = self.by_fold[fold]
        best: tuple[int, str, list[str]] | None = None
        for _ in range(attempts):
            chosen: list[BenignSentence] = []
            used: set[str] = set()
            if rng.random() < self.imperative_share and self.imperative_by_fold[fold]:
                first = rng.choice(self.imperative_by_fold[fold])
                chosen.append(first)
                used.add(first.sentence_id)
            while True:
                current = len(" ".join(s.text for s in chosen))
                remaining = length - current - (1 if chosen else 0)
                if remaining <= SENTENCE_MAX_CHARS:
                    break
                unused = [s for s in items if s.sentence_id not in used]
                if not unused:
                    break
                pick = rng.choice(unused)
                chosen.append(pick)
                used.add(pick.sentence_id)
            remaining = length - len(" ".join(s.text for s in chosen)) - (1 if chosen else 0)
            if remaining >= SENTENCE_MIN_CHARS:
                last = self._closest(fold, remaining, rng, used)
                if last is not None:
                    chosen.append(last)
            elif chosen and remaining < 0:
                continue
            text = " ".join(s.text for s in chosen)
            gap = abs(len(text) - length)
            if best is None or gap < best[0]:
                best = (gap, text, [s.sentence_id for s in chosen])
            if gap == 0:
                break
        assert best is not None
        if best[0] > self.tolerance:
            raise ValueError(f"No benign text within {self.tolerance} characters of length {length} in fold {fold}.")
        return best[1], best[2]

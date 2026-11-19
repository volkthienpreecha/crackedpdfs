"""Source loaders with provenance capture.

Every loader returns a SourceResult holding the provenance block that is written to sources.json and
the raw records that feed the normalisation pipeline. Loaders that cannot confirm a permissive licence
return an empty record list with a skip reason instead of raising.
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

USER_AGENT = "crackedpdfs-payloads/0.1 (+https://github.com/volkthienpreecha/crackedpdfs)"
HTTP_TIMEOUT = 60

V1_SOURCE = "crackedpdfs-v1"
V1_URL = "https://github.com/volkthienpreecha/crackedpdfs/blob/main/src/lib/prompt-injection-message-library.ts"
V1_LICENSE = "MIT"

OPI_FAKE_COMPLETION_TARGETS: tuple[str, ...] = (
    "sentiment_analysis",
    "spam_detection",
    "hate_detection",
    "summarization",
    "grammar_correction",
    "duplicate_sentence_detection",
    "natural_language_inference",
    "math",
)
# Upstream demonstration example containing a racial slur. Excluded from the pool on content grounds.
OPI_EXCLUDED_FILES: dict[str, str] = {
    "data/system_prompts/hate_detection_inject_med_long.txt": "demonstration example contains a racial slur",
}


@dataclass
class RawRecord:
    """One un-normalised payload candidate with its provenance fields."""

    text: str
    source: str
    source_record: str
    license: str
    url: str
    retrieved_at: str
    message_type: str | None = None


@dataclass
class SourceResult:
    """Provenance block for one source plus the records it produced."""

    name: str
    url: str
    license: str
    license_evidence: str
    retrieved_at: str
    revision: str | None
    records: list[RawRecord] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    raw_count: int = 0

    def manifest(self) -> dict[str, Any]:
        """Return the JSON-serialisable provenance block."""
        return {
            "name": self.name,
            "url": self.url,
            "license": self.license,
            "license_evidence": self.license_evidence,
            "retrieved_at": self.retrieved_at,
            "revision": self.revision,
            "raw_count": self.raw_count,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "notes": self.notes,
        }


def today() -> str:
    """Return the current UTC date as an ISO-8601 string."""
    return datetime.now(UTC).date().isoformat()


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def _get_text(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.text


def _get_json(session: requests.Session, url: str) -> Any:
    response = session.get(url, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()


# --------------------------------------------------------------------------------------------------
# Source 1: CrackedPDFs v1 message library (TypeScript)
# --------------------------------------------------------------------------------------------------

_V1_BLOCK_RE = re.compile(r"^\s{2}(\w+): \[\n(.*?)^\s{2}\],", re.MULTILINE | re.DOTALL)
_V1_STRING_RE = re.compile(r"`((?:[^`\\]|\\.)*)`")


def parse_v1_library(source: str) -> list[tuple[str, int, str]]:
    """Parse the v1 TypeScript message library into (message_type, index, content) triples.

    The parser targets the MESSAGE_CONTENT_BY_TYPE literal: every top-level key followed by an array of
    template strings. Backslash escapes inside the template strings are unescaped.
    """
    triples: list[tuple[str, int, str]] = []
    for block in _V1_BLOCK_RE.finditer(source):
        message_type = block.group(1)
        for index, match in enumerate(_V1_STRING_RE.finditer(block.group(2)), start=1):
            content = re.sub(r"\\(.)", r"\1", match.group(1))
            triples.append((message_type, index, content))
    return triples


def load_v1(path: Path, retrieved_at: str | None = None) -> SourceResult:
    """Load the 104 author-written v1 messages from the repository TypeScript file."""
    retrieved_at = retrieved_at or today()
    result = SourceResult(
        name=V1_SOURCE,
        url=V1_URL,
        license=V1_LICENSE,
        license_evidence="repository LICENSE file (MIT)",
        retrieved_at=retrieved_at,
        revision=None,
    )
    if not path.exists():
        result.skipped = True
        result.skip_reason = f"v1 library not found at {path}"
        return result
    triples = parse_v1_library(path.read_text(encoding="utf-8"))
    result.raw_count = len(triples)
    for message_type, index, content in triples:
        result.records.append(
            RawRecord(
                text=content,
                source=V1_SOURCE,
                source_record=f"{message_type}[{index:02d}]",
                license=V1_LICENSE,
                url=V1_URL,
                retrieved_at=retrieved_at,
                message_type=message_type,
            )
        )
    return result


# --------------------------------------------------------------------------------------------------
# Hugging Face datasets
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HFSpec:
    """Declarative description of a Hugging Face dataset source."""

    name: str
    repo: str
    expected_licenses: tuple[str, ...]
    select: Callable[[dict[str, Any]], str | None]
    record_label: Callable[[str, int, dict[str, Any]], str]
    config: str | None = None


def hf_dataset_info(session: requests.Session, repo: str) -> dict[str, Any]:
    """Return the Hub API metadata (revision sha and card data) for a dataset repository."""
    return _get_json(session, f"https://huggingface.co/api/datasets/{repo}")


def _hf_license(info: dict[str, Any]) -> str | None:
    card = info.get("cardData") or {}
    declared = card.get("license")
    if isinstance(declared, list):
        declared = declared[0] if declared else None
    if declared:
        return str(declared)
    for tag in info.get("tags", []):
        if isinstance(tag, str) and tag.startswith("license:"):
            return tag.split(":", 1)[1]
    return None


def load_hf(spec: HFSpec, retrieved_at: str | None = None) -> SourceResult:
    """Download a Hugging Face dataset pinned to its current revision and select injection rows."""
    retrieved_at = retrieved_at or today()
    url = f"https://huggingface.co/datasets/{spec.repo}"
    session = _session()
    info = hf_dataset_info(session, spec.repo)
    revision = info.get("sha")
    declared = _hf_license(info)
    result = SourceResult(
        name=spec.name,
        url=url,
        license=declared or "unknown",
        license_evidence=f"dataset card metadata at revision {revision}",
        retrieved_at=retrieved_at,
        revision=revision,
    )
    if declared is None or declared.lower() not in spec.expected_licenses:
        result.skipped = True
        result.skip_reason = f"dataset card license {declared!r} is not one of {spec.expected_licenses}"
        return result
    extra = (info.get("cardData") or {}).get("dataset_info") or {}
    if isinstance(extra, dict) and extra.get("license") and extra["license"] != declared:
        result.notes.append(f"dataset_info block also lists license {extra['license']!r}; card header is {declared!r}")

    from datasets import load_dataset

    dataset = load_dataset(spec.repo, spec.config, revision=revision)
    for split_name in sorted(dataset.keys()):
        split = dataset[split_name]
        result.raw_count += len(split)
        for index, row in enumerate(split):
            text = spec.select(row)
            if text is None:
                continue
            result.records.append(
                RawRecord(
                    text=text,
                    source=spec.name,
                    source_record=spec.record_label(split_name, index, row),
                    license=declared,
                    url=f"{url}/tree/{revision}",
                    retrieved_at=retrieved_at,
                )
            )
    return result


def _deepset_select(row: dict[str, Any]) -> str | None:
    return str(row["text"]) if int(row["label"]) == 1 else None


def _spml_select(row: dict[str, Any]) -> str | None:
    flag = row.get("Prompt injection")
    text = row.get("User Prompt")
    if flag is None or text is None:
        return None
    return str(text) if int(flag) == 1 else None


def _spml_label(split: str, index: int, row: dict[str, Any]) -> str:
    origin = row.get("Source")
    degree = row.get("Degree")
    suffix = f"|origin={origin}" if origin else ""
    return f"{split}[{index}]|degree={degree}{suffix}"


def _gandalf_select(row: dict[str, Any]) -> str | None:
    return str(row["text"])


def _jailbreak_select(row: dict[str, Any]) -> str | None:
    return str(row["prompt"]) if str(row["type"]).strip().lower() == "jailbreak" else None


def _plain_label(split: str, index: int, row: dict[str, Any]) -> str:
    return f"{split}[{index}]"


HF_SPECS: tuple[HFSpec, ...] = (
    HFSpec("deepset-prompt-injections", "deepset/prompt-injections", ("apache-2.0",), _deepset_select, _plain_label),
    HFSpec(
        "spml-chatbot-prompt-injection",
        "reshabhs/SPML_Chatbot_Prompt_Injection",
        ("mit",),
        _spml_select,
        _spml_label,
    ),
    HFSpec(
        "lakera-gandalf-ignore-instructions",
        "Lakera/gandalf_ignore_instructions",
        ("mit",),
        _gandalf_select,
        _plain_label,
    ),
    HFSpec(
        "jackhhao-jailbreak-classification",
        "jackhhao/jailbreak-classification",
        ("apache-2.0",),
        _jailbreak_select,
        _plain_label,
    ),
)


# --------------------------------------------------------------------------------------------------
# GitHub repositories
# --------------------------------------------------------------------------------------------------


@dataclass
class GitHubSnapshot:
    """Resolved default-branch commit and file listing for a GitHub repository."""

    repo: str
    sha: str
    paths: list[str]
    session: requests.Session

    def raw(self, path: str) -> str:
        """Fetch a file at the pinned commit."""
        return _get_text(self.session, f"https://raw.githubusercontent.com/{self.repo}/{self.sha}/{path}")


def github_snapshot(repo: str, session: requests.Session | None = None) -> GitHubSnapshot:
    """Resolve the default branch head and recursive tree for a repository."""
    session = session or _session()
    meta = _get_json(session, f"https://api.github.com/repos/{repo}")
    branch = meta["default_branch"]
    head = _get_json(session, f"https://api.github.com/repos/{repo}/commits/{branch}")
    sha = head["sha"]
    tree = _get_json(session, f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1")
    paths = [entry["path"] for entry in tree.get("tree", []) if entry.get("type") == "blob"]
    return GitHubSnapshot(repo=repo, sha=sha, paths=paths, session=session)


def confirm_mit(license_text: str) -> bool:
    """Return True when a LICENSE file is the MIT licence."""
    head = license_text.strip().splitlines()[0].strip().lower() if license_text.strip() else ""
    return head == "mit license" or "permission is hereby granted, free of charge" in license_text.lower()


class _ClassConstEvaluator(ast.NodeVisitor):
    """Resolve a GOAL expression built from string constants, f-strings, and class-level constants."""

    def __init__(self, constants: dict[str, str]) -> None:
        self.constants = constants

    def evaluate(self, node: ast.AST) -> str:
        """Evaluate node to a string, raising KeyError or TypeError when it cannot be resolved statically."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(self.evaluate(part) for part in node.values)
        if isinstance(node, ast.FormattedValue):
            return self.evaluate(node.value)
        if isinstance(node, ast.Name):
            return self.constants[node.id]
        if isinstance(node, ast.Attribute):
            return self.constants[node.attr]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.evaluate(node.left) + self.evaluate(node.right)
        raise TypeError(f"unsupported node {type(node).__name__}")


def extract_agentdojo_goals(source: str) -> Iterator[tuple[str, str]]:
    """Yield (class_name, goal) pairs from an AgentDojo injection_tasks.py module.

    Module-level and class-level simple string assignments are collected so that f-string GOALs that
    interpolate constants such as attacker addresses resolve to the concrete text used by the benchmark.
    """
    tree = ast.parse(source)
    module_constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_constants[target.id] = node.value.value
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        constants = dict(module_constants)
        goal_node: ast.AST | None = None
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            names = [t.id for t in item.targets if isinstance(t, ast.Name)]
            if "GOAL" in names:
                goal_node = item.value
                continue
            if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                for name in names:
                    constants[name] = item.value.value
        if goal_node is None:
            continue
        try:
            yield node.name, _ClassConstEvaluator(constants).evaluate(goal_node)
        except (KeyError, TypeError):
            continue


def load_agentdojo(retrieved_at: str | None = None) -> SourceResult:
    """Load every injection task GOAL from the AgentDojo default suites."""
    retrieved_at = retrieved_at or today()
    repo = "ethz-spylab/agentdojo"
    url = f"https://github.com/{repo}"
    snapshot = github_snapshot(repo)
    result = SourceResult(
        name="agentdojo-injection-tasks",
        url=url,
        license="MIT",
        license_evidence=f"LICENSE file at commit {snapshot.sha}",
        retrieved_at=retrieved_at,
        revision=snapshot.sha,
    )
    if not confirm_mit(snapshot.raw("LICENSE")):
        result.skipped = True
        result.license = "unknown"
        result.skip_reason = "LICENSE file is not the MIT licence"
        return result
    pattern = re.compile(r"^src/agentdojo/default_suites/(v[^/]+)/([^/]+)/injection_tasks\.py$")
    for path in sorted(snapshot.paths):
        match = pattern.match(path)
        if not match:
            continue
        suite_version, suite = match.groups()
        for class_name, goal in extract_agentdojo_goals(snapshot.raw(path)):
            result.raw_count += 1
            result.records.append(
                RawRecord(
                    text=goal,
                    source=result.name,
                    source_record=f"{suite_version}/{suite}/{class_name}",
                    license="MIT",
                    url=f"{url}/blob/{snapshot.sha}/{path}",
                    retrieved_at=retrieved_at,
                )
            )
    result.notes.append("GOAL f-strings resolved against class constants (attacker addresses, IBANs, links)")
    return result


def parse_fake_completions(utils_source: str) -> dict[str, str]:
    """Parse the FAKE_COMPLETIONS dictionary literal from Open-Prompt-Injection attackers/utils.py."""
    tree = ast.parse(utils_source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "FAKE_COMPLETIONS" for t in node.targets
        ):
            value = ast.literal_eval(node.value)
            return {str(k): str(v) for k, v in value.items()}
    return {}


def _ignore_form(instruction: str) -> str:
    """Mirror the upstream attacker rewrite of a trailing full stop into a colon."""
    return instruction[:-1] + ":" if instruction.endswith(".") else instruction


def compose_opi_payloads(
    instruction: str,
    fake_completions: dict[str, str],
    inject_data: str = "",
) -> list[tuple[str, str]]:
    """Return (attack_name, payload) pairs mirroring the five Open-Prompt-Injection attacker templates.

    The escape-character attack differs from the naive attack only by a leading newline, which whitespace
    normalisation removes, so it is folded into the naive template. The fake-completion and combined attacks
    are expanded over every target task because the upstream experiment matrix pairs each injected task
    with each target task.
    """
    instruction = _ignore_form(instruction.strip())
    tail = f" {inject_data}" if inject_data else ""
    payloads = [("naive", f"{instruction}{tail}"), ("ignore", f"Ignore previous instructions. {instruction}{tail}")]
    for target, fake in sorted(fake_completions.items()):
        payloads.append((f"fake_completion|target={target}", f"{fake} {instruction}{tail}"))
        payloads.append((f"combine|target={target}", f"{fake}\nIgnore previous instructions. {instruction}{tail}"))
    return payloads


def load_open_prompt_injection(retrieved_at: str | None = None) -> SourceResult:
    """Load injected instruction templates and attacker compositions from Open-Prompt-Injection."""
    retrieved_at = retrieved_at or today()
    repo = "liu00222/Open-Prompt-Injection"
    url = f"https://github.com/{repo}"
    snapshot = github_snapshot(repo)
    result = SourceResult(
        name="open-prompt-injection",
        url=url,
        license="MIT",
        license_evidence=f"LICENSE file at commit {snapshot.sha}",
        retrieved_at=retrieved_at,
        revision=snapshot.sha,
    )
    if not confirm_mit(snapshot.raw("LICENSE")):
        result.skipped = True
        result.license = "unknown"
        result.skip_reason = "LICENSE file is not the MIT licence"
        return result
    fake_completions = parse_fake_completions(snapshot.raw("OpenPromptInjection/attackers/utils.py"))
    instructions: list[tuple[str, str, str]] = []
    for path in sorted(snapshot.paths):
        if not re.match(r"^data/system_prompts/[^/]+_inject[^/]*\.txt$", path):
            continue
        if path in OPI_EXCLUDED_FILES:
            result.notes.append(f"excluded {path}: {OPI_EXCLUDED_FILES[path]}")
            continue
        text = snapshot.raw(path).strip().splitlines()[0].strip()
        instructions.append((path, text, ""))
    compromise_source = snapshot.raw("OpenPromptInjection/tasks/CompromiseTask.py")
    compromise = re.search(r"self\.instruction = '([^']+)'", compromise_source)
    compromise_data = re.search(r"return '([^']+)', 'compromised'", compromise_source)
    if compromise and compromise_data:
        instructions.append(
            ("OpenPromptInjection/tasks/CompromiseTask.py", compromise.group(1), compromise_data.group(1))
        )
    for path, instruction, data in instructions:
        for attack, payload in compose_opi_payloads(instruction, fake_completions, data):
            result.raw_count += 1
            result.records.append(
                RawRecord(
                    text=payload,
                    source=result.name,
                    source_record=f"{Path(path).name}|{attack}",
                    license="MIT",
                    url=f"{url}/blob/{snapshot.sha}/{path}",
                    retrieved_at=retrieved_at,
                )
            )
    result.notes.append(
        "payloads are the attacker templates (naive, ignore, fake completion, combined) applied to each injected "
        "instruction with the dataset-specific injected sample omitted"
    )
    return result


def all_loaders(v1_path: Path) -> list[Callable[[], SourceResult]]:
    """Return the ordered list of loader callables for a build."""
    loaders: list[Callable[[], SourceResult]] = [lambda: load_v1(v1_path)]
    loaders.extend(lambda spec=spec: load_hf(spec) for spec in HF_SPECS)
    loaders.append(load_agentdojo)
    loaders.append(load_open_prompt_injection)
    return loaders

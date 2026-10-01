"""Text normalisation, stable ids, length filters, language detection, and message-type rules."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

MIN_CHARS = 20
MAX_CHARS = 1200

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
UNCLASSIFIED = "unclassified"

_WS_RE = re.compile(r"\s+")
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("'", "'"),
    ("`", "`"),
    ("“", "”"),
    ("‘", "’"),
    ("«", "»"),
)


def normalize_text(text: str) -> str:
    """Return the canonical form of a payload text.

    Applies NFC normalisation, collapses every whitespace run (including newlines) to a single
    space, trims, and repeatedly strips one matching pair of surrounding quotes.
    """
    out = unicodedata.normalize("NFC", text)
    out = _WS_RE.sub(" ", out).strip()
    changed = True
    while changed and len(out) >= 2:
        changed = False
        for opening, closing in _QUOTE_PAIRS:
            if out.startswith(opening) and out.endswith(closing):
                out = out[len(opening) : len(out) - len(closing)].strip()
                changed = True
                break
    return out


def is_valid_length(text: str, minimum: int = MIN_CHARS, maximum: int = MAX_CHARS) -> bool:
    """Return True when the text length is within the inclusive [minimum, maximum] window."""
    return minimum <= len(text) <= maximum


def payload_id(normalized_text: str) -> str:
    """Return the stable id: "pl-" plus the first 12 hex digits of sha256 over the normalised text."""
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return f"pl-{digest[:12]}"


def dedupe_key(normalized_text: str) -> str:
    """Return the case-insensitive key used for exact-duplicate removal."""
    return normalized_text.casefold()


def detect_language(text: str) -> str:
    """Return an ISO 639-1 language code using langdetect, or "und" when detection fails."""
    try:
        from langdetect import DetectorFactory, detect
        from langdetect.lang_detect_exception import LangDetectException
    except ImportError:  # pragma: no cover - dependency is declared, guard keeps tests hermetic
        return "und"
    DetectorFactory.seed = 0
    try:
        return str(detect(text))
    except LangDetectException:
        return "und"


@dataclass(frozen=True)
class TypeRule:
    """One message type with the ordered list of case-insensitive regular expressions that vote for it."""

    message_type: str
    patterns: tuple[str, ...]
    description: str

    def compiled(self) -> list[re.Pattern[str]]:
        """Compile the rule patterns (case-insensitive)."""
        return [re.compile(p, re.IGNORECASE) for p in self.patterns]


# Rules are listed in priority order. A message is assigned the type with the most matching
# patterns; ties resolve to the earlier rule. Messages matching nothing become "unclassified".
TYPE_RULES: tuple[TypeRule, ...] = (
    TypeRule(
        "summarization_steering",
        (
            r"\bsummar(y|ies|i[sz]e|i[sz]ed|i[sz]ing|i[sz]ation)\b",
            r"\b(takeaway|headline|main (intent|point|topic)|central point|primary conclusion)\b",
            r"\b(hidden|concealed|embedded)\b.{0,60}\b(document|takeaway|headline|summary)\b",
            r"\b(document|content|prose)\b.{0,60}\b(hidden|concealed|embedded|override language)\b",
        ),
        "manipulates what a summary should foreground or omit",
    ),
    TypeRule(
        "system_extraction",
        (
            r"\bsystem (prompt|message|instructions?)\b",
            r"\bwhat instructions\b",
            r"\b(repeat|reveal|print|show|output|display|dump|recite|disclose|leak|tell me|give me|what (are|were|"
            r"is))\b"
            r".{0,60}\b(your|the|its|hidden|secret|original|initial|internal|confidential|above)\b"
            r".{0,30}\b(instructions?|prompts?|rules|directives?|configuration|guidelines)\b",
            r"\b(initial|initiali[sz]ation|startup|original|hidden|secret|confidential)\b.{0,20}\b(prompt|"
            r"instructions?|directives?)\b",
            r"\b(instructions|rules|prompt)\b.{0,40}\b(verbatim|word for word|in full)\b",
            r"\b(hidden|concealed|confidential|internal|privileged|secret|non-user) (instructions?|directives?|rules|"
            r"prompt)\b",
        ),
        "asks the model to disclose its system prompt, hidden instructions, or governing rules",
    ),
    TypeRule(
        "data_exfiltration",
        (
            r"\b(password|passwords|passcode|passphrase|credentials?|api[ -]?keys?|secret keys?|access tokens?|session "
            r"tokens?|private keys?)\b",
            r"\bexfiltrat",
            r"\b(secret|secrets|secret word|secret code|secret phrase)\b",
            r"\b(send|forward|post|upload|email|transmit|leak|share)\b.{0,80}\b(to|at)\b.{0,60}\b(https?://|@|\.com|"
            r"\.net|\.org|iban|account)",
            r"\b(iban|routing number|account number|credit card|ssn|social security)\b",
            r"\bphishing\b",
            r"\b(confidential|sensitive|private|secret-like|token-like|credential) "
            r"(values?|strings?|identifiers?|metadata|data|information|material|references?)\b",
            r"\b(reveal|expose|extract|list|collect|output|pull out|enumerate)\b.{0,60}"
            r"\b(credentials?|identifiers?|secrets?|tokens?|metadata|private values)\b",
        ),
        "seeks passwords, keys, tokens, secrets, or routes private data to an attacker-controlled destination",
    ),
    TypeRule(
        "agent_tool_manipulation",
        (
            r"\b(use|call|invoke|run|execute|trigger)\b.{0,20}\b(tools?|functions?|browser|plugins?|apis?|shell|"
            r"terminal|code interpreter)\b",
            r"\b(send|forward|delete|schedule|create|modify|change|transfer|book|cancel|update|reserve|make)\b.{0,60}"
            r"\b(an? )?(emails?|calendar|events?|transactions?|payments?|messages?|files?|reservations?|bookings?|"
            r"appointments?)\b",
            r"\b(tool|function)[ _]?calls?\b",
            r"\b(local|accessible|private) (files|directories|environment|logs|artifacts)\b",
            r"\btool (use|usage|calls?|output)\b",
            r"\b(file|browser|execution|search|shell) tools?\b",
            r"\b(inspect|gather|enumerate|query)\b.{0,40}\b(environment|logs|runtime state|artifacts|hidden state)\b",
        ),
        "steers an agent toward tool, file, email, calendar, or payment actions",
    ),
    TypeRule(
        "refusal_suppression",
        (
            r"\b(do not|don't|never|must not|cannot|can't)\b.{0,15}\b(refuse|decline|apologi[sz]e|warn|hedge|lecture|"
            r"moralize|moralise|censor)",
            r"\bwithout\b.{0,20}\b(refus\w*|warnings?|disclaimers?|caveats?|restrictions?|limitations?|filters?|"
            r"censorship)\b",
            r"\bno (disclaimers?|warnings?|restrictions?|limitations?|filters?|censorship|moral\w*|ethical\w*)\b",
            r"\b(unfiltered|uncensored|unrestricted|unethical|immoral)\b",
            r"\b(DAN|jailbreak|jailbroken|developer mode|god mode|evil mode)\b",
            r"\b(you (can|will) do anything|free of (any|all) restrictions|no longer bound|break free|not bound by)\b",
            r"\b(answer|respond|comply|continue|proceed) (directly|anyway|regardless|immediately|plainly)\b",
            r"\b(refus\w*|disclaimers?|caveats?|hedge|safety (policy|framing|rules?)|apology language|limitation "
            r"statements)\b",
            r"\b(just|simply) comply\b",
        ),
        "suppresses refusals, disclaimers, or safety framing, including jailbreak personas",
    ),
    TypeRule(
        "policy_framing",
        (
            r"\b(policy|policies|compliance|audit|exemption|exception|authori[sz]ed|authori[sz]ation|clearance|"
            r"permitted)\b",
            r"\b(red[- ]team|penetration test|pentest|security (evaluation|test|review|research)|evaluation (mode|"
            r"environment|rubric))\b",
            r"\b(for|as part of|this is) (an? )?(research|educational|testing|academic|training|hypothetical|fictional|"
            r"roleplay) (purposes?|exercise|scenario|session)\b",
            r"\b(i am|i'm|this is|speaking as) (the |your |an? )?(developer|administrator|admin|creator|owner|engineer|"
            r"openai|anthropic|supervisor|ceo)\b",
            r"\b(developer|admin|administrator|maintenance|debug|testing|override) (mode|access|privileges?)\b",
            r"\b(i know|i understand|i realize|i realise|i am aware) (that )?(you|you're|you are)\b.{0,40}"
            r"\b(not (allowed|supposed|permitted|able)|usually|normally|typically|can't|cannot)\b",
            r"\b(experimental feature|special exception|make an exception|just this once|one-time exception)\b",
            r"\b(theoretically|hypothetically|in theory|as a thought experiment)\b",
        ),
        "invokes a fake policy, exemption, authority, or testing context to legitimise compliance",
    ),
    TypeRule(
        "instruction_override",
        (
            r"\b(ignore|disregard|forget|override|overrule|discard|erase|skip|drop|neglect|abandon)\b.{0,40}"
            r"\b(previous|prior|above|earlier|all|preceding|initial|original|former|existing|those|these|any)\b.{0,30}"
            r"\b(instructions?|rules?|prompts?|directives?|text|context|guidelines?|constraints?|commands?|messages?|"
            r"conversation)\b",
            r"\b(ignore|disregard|forget) (everything|all|what)\b",
            r"\b(new|replacement|updated|real) (instructions?|rules?|directives?|task|objective)\b",
            r"\bfrom now on\b",
            r"\b(stop|halt)\b.{0,30}\b(new|instead|now|and)\b",
            r"\b(supersed|obsolete|cancell?ed|revoked|no longer (apply|valid)|replaces? all)\b",
            r"\b(vergiss|vergessen sie|ignorier\w*|missachte\w*|verwerfe\w*)\b",
            r"\b(vorherigen|bisherigen|obigen|alles davor|alle vorherigen|vorige)\b",
            r"\bab jetzt\b",
            r"\b(opposite of|reset|defy|defied|go(es|ing)? against|went against|contrary to|break|violate)\b.{0,30}"
            r"\b(instructions?|rules?|prompts?|protocol|guidelines?|programming|directives?)\b",
            r"\b(even if|although|regardless of whether) (it|this|that) (goes|is) against\b",
        ),
        "tells the model to drop or replace its existing instructions (English and German cues)",
    ),
    TypeRule(
        "task_hijack",
        (
            r"\b(your|the) (real|actual|true|new|only|main) (task|job|goal|objective|instruction)\b",
            r"\b(instead of|rather than|instead,?|but first|before (you )?(do|answer|respond|continue|start))\b",
            r"^(write|answer|tell me|say|print|output|are the following|does the following|please (write|identify|"
            r"answer|say)|"
            r"correct|translate|classify|repeat (the following|after me)|as an? .{0,40}tool|calculate|identify)\b",
            r"\b(write|say|print|output|respond with|reply with|answer with)\b.{0,40}\b(only|just|exactly|the (word|"
            r"phrase))\b",
            r"\b(story|poem|joke|haiku|song|limerick)\b",
        ),
        "replaces the intended task with a different one (a competing instruction)",
    ),
)

_COMPILED_RULES: list[tuple[str, list[re.Pattern[str]]]] = [(rule.message_type, rule.compiled()) for rule in TYPE_RULES]


def rule_scores(text: str) -> dict[str, int]:
    """Return the number of matching patterns per message type for a text."""
    return {name: sum(1 for pattern in patterns if pattern.search(text)) for name, patterns in _COMPILED_RULES}


def classify_message_type(text: str) -> str:
    """Assign a message type by keyword rules, or "unclassified" when nothing matches.

    The type with the highest number of matching patterns wins. Ties resolve in favour of the
    rule that appears first in TYPE_RULES (the more specific rules are listed first).
    """
    best_type = UNCLASSIFIED
    best_score = 0
    for name, patterns in _COMPILED_RULES:
        score = sum(1 for pattern in patterns if pattern.search(text))
        if score > best_score:
            best_type, best_score = name, score
    return best_type

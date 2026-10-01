"""Licensed, id-tagged, near-duplicate-clustered prompt-injection payload pool for CrackedPDFs v2."""

from crackedpdfs_payloads.cluster import cluster_texts, nearest_jaccard, shingles
from crackedpdfs_payloads.normalize import (
    MESSAGE_TYPES,
    classify_message_type,
    normalize_text,
    payload_id,
)

__all__ = [
    "MESSAGE_TYPES",
    "classify_message_type",
    "cluster_texts",
    "nearest_jaccard",
    "normalize_text",
    "payload_id",
    "shingles",
]

__version__ = "0.1.0"

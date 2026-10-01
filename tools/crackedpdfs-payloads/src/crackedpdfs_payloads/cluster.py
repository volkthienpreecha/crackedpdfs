"""MinHash and LSH near-duplicate clustering over character shingles."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from datasketch import MinHash, MinHashLSH

SHINGLE_SIZE = 5
NUM_PERM = 128
LSH_THRESHOLD = 0.7
CLUSTER_PREFIX = "pc-"
CLUSTER_PAD = 6


def shingles(text: str, k: int = SHINGLE_SIZE) -> set[str]:
    """Return the set of lowercase character k-grams of a text.

    Texts shorter than k produce a single shingle equal to the whole text so that every message has
    a non-empty signature.
    """
    lowered = text.casefold()
    if len(lowered) <= k:
        return {lowered}
    return {lowered[i : i + k] for i in range(len(lowered) - k + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    """Return the exact Jaccard similarity of two shingle sets."""
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def minhash(shingle_set: Iterable[str], num_perm: int = NUM_PERM) -> MinHash:
    """Return the MinHash signature of a shingle set."""
    signature = MinHash(num_perm=num_perm, seed=1)
    for shingle in shingle_set:
        signature.update(shingle.encode("utf-8"))
    return signature


class UnionFind:
    """Minimal union-find over integer indices with path compression."""

    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        """Return the root of index."""
        root = index
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[index] != root:
            self.parent[index], index = root, self.parent[index]
        return root

    def union(self, a: int, b: int) -> None:
        """Merge the sets containing a and b."""
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def cluster_texts(
    texts: Sequence[str],
    *,
    threshold: float = LSH_THRESHOLD,
    num_perm: int = NUM_PERM,
    k: int = SHINGLE_SIZE,
) -> list[str]:
    """Cluster texts into near-duplicate groups and return one cluster id per input text.

    MinHash signatures over character k-grams are indexed with LSH at the given Jaccard threshold,
    candidate pairs are joined with union-find, and each connected component becomes one cluster.
    Cluster ids are "pc-" plus a zero-padded index assigned in order of first appearance.
    """
    signatures = [minhash(shingles(text, k), num_perm) for text in texts]
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    for index, signature in enumerate(signatures):
        lsh.insert(str(index), signature)
    uf = UnionFind(len(texts))
    for index, signature in enumerate(signatures):
        for key in lsh.query(signature):
            uf.union(index, int(key))
    labels: dict[int, str] = {}
    cluster_ids: list[str] = []
    for index in range(len(texts)):
        root = uf.find(index)
        if root not in labels:
            labels[root] = f"{CLUSTER_PREFIX}{len(labels):0{CLUSTER_PAD}d}"
        cluster_ids.append(labels[root])
    return cluster_ids


def nearest_jaccard(
    texts: Sequence[str],
    reference: Sequence[str],
    *,
    k: int = SHINGLE_SIZE,
    exclude_self: bool = True,
) -> list[float]:
    """Return, for each text, the maximum exact Jaccard similarity to any reference text.

    When exclude_self is True a text that is itself present in the reference set is compared only
    against the other reference texts, so reference members report their nearest distinct neighbour.
    """
    reference_shingles = [shingles(text, k) for text in reference]
    reference_index: dict[str, int] = {text: i for i, text in enumerate(reference)}
    results: list[float] = []
    for text in texts:
        own = shingles(text, k)
        self_index = reference_index.get(text) if exclude_self else None
        best = 0.0
        for i, ref in enumerate(reference_shingles):
            if i == self_index:
                continue
            score = jaccard(own, ref)
            if score > best:
                best = score
        results.append(round(best, 4))
    return results

"""Evaluation protocols that hold out payloads as well as documents.

The paper v1 protocol groups splits by base document only. Every injected
PDF draws its payload from a pool of 104 messages, and all 104 messages
appear in train, validation, and test. These protocols make the payload a
second grouping dimension so that a detector can be scored on documents it
has not seen, payloads it has not seen, and both at once.

Cell naming follows the pair-input evaluation literature (Park and Marcotte,
Nature Methods 2012; Pahikkala et al., Briefings in Bioinformatics 2015):

    C2   document unseen, payload seen
    C2p  document seen, payload unseen
    C3   document unseen, payload unseen

Triads are the unit of assignment. A triad is one benign original, one
matched benign confounder, and one injected PDF. When a payload fold is
held out, every triad that uses a payload from that fold is removed from
training in full, so confounders built for a held-out payload never reach
the training set either.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRIAD_COLUMN = "triad_id"
DOC_COLUMN = "base_pdf_id"
PAYLOAD_COLUMN = "message_variant_id"
TYPE_COLUMN = "message_type"
ROLE_COLUMN = "pdf_role"


@dataclass(frozen=True)
class FoldAssignment:
    """Fold index per document and per payload."""

    doc_fold: dict[str, int]
    payload_fold: dict[str, int]
    n_folds: int


def assign_folds(labels: pd.DataFrame, n_folds: int = 5, random_state: int = 42) -> FoldAssignment:
    """Assign documents and payloads to folds independently.

    Documents are shuffled and dealt round-robin. Payloads are dealt
    round-robin within each message type so that every fold keeps every
    type, which matters because the pool holds only 13 payloads per type.
    """
    rng = np.random.default_rng(random_state)
    docs = sorted(labels[DOC_COLUMN].astype(str).unique())
    rng.shuffle(docs)
    doc_fold = {doc: index % n_folds for index, doc in enumerate(docs)}

    injected = labels[labels["label"].astype(int) == 1]
    payload_fold: dict[str, int] = {}
    for _, group in injected.groupby(TYPE_COLUMN, sort=True):
        payloads = sorted(group[PAYLOAD_COLUMN].astype(str).unique())
        rng.shuffle(payloads)
        for index, payload in enumerate(payloads):
            payload_fold[payload] = index % n_folds
    return FoldAssignment(doc_fold=doc_fold, payload_fold=payload_fold, n_folds=n_folds)


def triad_table(labels: pd.DataFrame) -> pd.DataFrame:
    """One row per triad with its document and payload identifiers."""
    injected = labels[labels["label"].astype(int) == 1]
    table = injected[[TRIAD_COLUMN, DOC_COLUMN, PAYLOAD_COLUMN, TYPE_COLUMN, "attack_family"]].copy()
    table = table.drop_duplicates(TRIAD_COLUMN).reset_index(drop=True)
    if table[TRIAD_COLUMN].duplicated().any():
        raise ValueError("A triad maps to more than one injected PDF.")
    missing = set(labels[TRIAD_COLUMN].astype(str)) - set(table[TRIAD_COLUMN].astype(str))
    if missing:
        raise ValueError(f"{len(missing)} triads have no injected member.")
    return table


def both_out_fold(
    labels: pd.DataFrame,
    assignment: FoldAssignment,
    fold: int,
) -> dict[str, pd.DataFrame]:
    """Training rows and the three test cells for one fold.

    Returns a dict with keys ``train``, ``C2``, ``C2p``, ``C3``. Each value
    holds full label rows (originals, confounders, and injected PDFs) for
    the triads in that cell.
    """
    triads = triad_table(labels)
    doc_fold = triads[DOC_COLUMN].astype(str).map(assignment.doc_fold)
    payload_fold = triads[PAYLOAD_COLUMN].astype(str).map(assignment.payload_fold)
    if doc_fold.isna().any() or payload_fold.isna().any():
        raise ValueError("Every triad must map to a document fold and a payload fold.")
    doc_held = doc_fold == fold
    payload_held = payload_fold == fold
    cells = {
        "train": triads[~doc_held & ~payload_held],
        "C2": triads[doc_held & ~payload_held],
        "C2p": triads[~doc_held & payload_held],
        "C3": triads[doc_held & payload_held],
    }
    by_triad = labels.set_index(TRIAD_COLUMN, drop=False)
    return {
        name: by_triad.loc[by_triad.index.isin(cell[TRIAD_COLUMN])].reset_index(drop=True)
        for name, cell in cells.items()
    }


def family_holdout(labels: pd.DataFrame, family: str) -> dict[str, pd.DataFrame]:
    """Paper v1 leave-one-attack-family-out protocol.

    Every base document that carries at least one triad of the held-out
    family moves to the test set in full, including its other triads.
    """
    family_docs = set(labels.loc[labels["attack_family"].astype(str) == family, DOC_COLUMN].astype(str))
    if not family_docs:
        raise ValueError(f"No rows for attack family {family!r}.")
    is_test = labels[DOC_COLUMN].astype(str).isin(family_docs)
    return {"train": labels[~is_test].reset_index(drop=True), "test": labels[is_test].reset_index(drop=True)}


def carve_validation(
    train: pd.DataFrame, fraction: float = 0.1, random_state: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out a document-grouped validation slice for threshold selection."""
    rng = np.random.default_rng(random_state)
    docs = sorted(train[DOC_COLUMN].astype(str).unique())
    rng.shuffle(docs)
    n_val = max(1, int(round(len(docs) * fraction)))
    val_docs = set(docs[:n_val])
    is_val = train[DOC_COLUMN].astype(str).isin(val_docs)
    return train[~is_val].reset_index(drop=True), train[is_val].reset_index(drop=True)

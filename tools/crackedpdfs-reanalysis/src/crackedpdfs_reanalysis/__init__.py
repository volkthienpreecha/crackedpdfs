"""Re-analysis of the CrackedPDFs paper v1 corpus under stricter evaluation protocols.

The frozen detector under ``lightweight-detector/`` is byte-pinned for paper
reproducibility and is never modified. This package imports its training
code, feeds it the frozen release tables and a persisted text cache, and
evaluates it under document-and-payload holdout, symmetric sanitization,
and leave-one-family-out protocols.
"""

__version__ = "0.1.0"

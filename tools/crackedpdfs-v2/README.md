# crackedpdfs-v2

Content pools for CrackedPDFs benchmark v2. Status: work in progress. The corpus builder and evaluation harness are not written yet.

`prompt-injection` `benchmark` `pdf` `held-out-splits`

## What is here

| Module | Purpose |
| --- | --- |
| `content.py` | Loads typed English payloads from `tools/crackedpdfs-payloads`, deals payload clusters into content folds stratified by message type, builds a benign sentence pool from real documents (folded by source document), and draws benign text of the same character length as a payload. About half of the benign texts open with an imperative sentence, so instruction mood alone does not identify the injected text. |

The injector accepts two optional config keys for v2: `target_pages`, which injects into the listed zero-based pages only, and `visibility_control`, which allows the visible member of an item.

## Planned design

Each base document yields items of four members plus the original: the instruction hidden, benign text of equal length hidden, the instruction visible, and the benign text visible. Text is identical across visibility, so a detector that reads only text cannot separate hidden from visible, and a detector that sees only hiddenness cannot separate instruction from benign. See `paper-v2/V2-HANDOFF.md`.

# crackedpdfs-v2

Content pools and page placement for CrackedPDFs benchmark v2. This is work in progress: the corpus builder and the evaluation harness are not written yet.

`prompt-injection` `benchmark` `pdf` `held-out-splits` `shortcut-audit`

## What is here

| Module | Purpose |
| --- | --- |
| `content.py` | Loads the payloads and the benign text, splits both into content folds, and draws a benign text to pair with each payload. |
| `placement.py` | Finds blank areas of a rendered page, so text that is meant to be hidden does not land on top of existing content. |
| `scripts/stress_v2.py` | Runs the audits behind `paper-v2/V2-STRESS-TEST.md` (modes `content`, `inject` and `anchor`). |

### `content.py`

- **Payloads:** loads typed English payloads from `tools/crackedpdfs-payloads`.
- **Payload folds:** splits payload clusters into content folds by message type, largest clusters first, so every fold gets a near-equal number of rows of each type.
- **Benign pool:** builds a pool of benign sentences from real documents, with each source document assigned to a single fold.
- **Matching:** draws a benign text of exactly the payload's character length that also copies the payload's surface style. That covers whether it addresses the reader ("you"), whether it speaks in the first person, and how it ends.
- **Reuse cap:** no sentence opens more than `max_reuse` texts (8 by default).

### `placement.py`

- **Anchors:** ranks candidate anchors by how much ink a rendered page has under the box the payload will occupy.
- **Use:** the builder passes a blank anchor to the injector's `anchor` key.

## Injector keys used by v2

The primary injector takes three optional config keys:

| Key | Effect |
| --- | --- |
| `target_pages` | Injects into the listed zero-based pages only. |
| `visibility_control` | Allows the visible member of an item. |
| `anchor` | Moves a flowed in-page payload to `[x, y]`, given as fractions of the visible page box. The placement contract is still enforced. |

## Planned design

Each base document yields items of four members plus the original:

| | Hidden | Visible |
| --- | --- | --- |
| Instruction | instruction hidden | instruction visible |
| Benign text of equal length | benign text hidden | benign text visible |

The text is identical across visibility, so a detector that reads only text cannot separate hidden from visible. A detector that sees only hiddenness cannot separate instruction from benign.

See `paper-v2/REVISION-PLAN.md` for the design and `paper-v2/V2-STRESS-TEST.md` for the audits.

## Requirements found by the stress tests

- **Pool size:** build the benign pool from at least 500 documents. With 34 documents, matching fails for 5% of payloads, and the "you" and first-person shortcuts come back (AUC 0.83 and 0.86).
- **Disjoint sources:** the benign source documents must not overlap the base documents or the real negatives.
- **Base screening:** drop base documents that pypdf cannot extract before injection. One GovDocs1 file in 150 fails this check.

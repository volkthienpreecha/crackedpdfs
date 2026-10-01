# Release table audit

## Split consistency

Rows compared: 29,322. Rows whose `dataset_split` column agrees with the frozen split file: 19,281 (65.8%).

| frozen split | test | train | validation |
| --- | ---: | ---: | ---: |
| test | 165 | 2,481 | 273 |
| train | 2,517 | 18,960 | 2,289 |
| validation | 129 | 2,352 | 156 |

## Payload overlap

| Quantity | Value |
| --- | ---: |
| Injected PDFs | 9,774 |
| Distinct payloads | 104 |
| Payloads present in train, validation, and test | 104 |
| Uses per payload (min / median / max) | 72 / 94 / 114 |
| Test injected PDFs | 973 |
| Test injected PDFs whose payload appears in training | 973 |
| Test payloads never seen in training | 0 |

## File identity

- `labels.parquet`: `41838450b245e22761293db57f05997cd9819a86abe2cc1f362f7cccc9724927`
- `splits.json`: `5ab6a6236cd13613fb194896e38eb6f85c131746df799485e800eab6cff338c3`
- `metadata.parquet`: `41838450b245e22761293db57f05997cd9819a86abe2cc1f362f7cccc9724927`

Byte-identical pairs: labels.parquet = metadata.parquet

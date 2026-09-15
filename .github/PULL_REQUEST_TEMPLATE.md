## What changed

<!-- One or two sentences. Link the issue if there is one. -->

## Why

<!-- The problem this solves, with evidence (a failing test, an audit number, a report). -->

## Benchmark impact

- [ ] No effect on generated PDFs, labels, splits, features, or metrics
- [ ] Changes generated PDFs or labels (describe which families and regimes)
- [ ] Changes paper-facing claims or files under `paper-v1/` (explain why this is a documented correction, not an in-place rewrite)

## Validation

<!-- Paste the exact commands you ran and their results. -->

```bash
make smoke
make lint
```

## Checklist

- [ ] Placement labels still match measured geometry (`crackedpdfs-audit` or the injector placement contract)
- [ ] Metric names match the artifact fields that produced them
- [ ] No generated PDFs, databases, model binaries, secrets, or private paths are committed
- [ ] `CHANGELOG.md` updated under **Unreleased** for user-visible changes

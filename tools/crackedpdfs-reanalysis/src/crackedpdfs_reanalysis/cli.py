"""Command line entry point: ``crackedpdfs-reanalysis <command> [options]``."""

from __future__ import annotations

import sys

COMMANDS = {
    "run": (
        "crackedpdfs_reanalysis.run",
        "Train and evaluate the frozen detectors under the re-analysis protocols.",
    ),
    "text-cache": (
        "crackedpdfs_reanalysis.text_cache",
        "Extract pypdf text once for every PDF in the labels table.",
    ),
    "release-audit": (
        "crackedpdfs_reanalysis.release_audit",
        "Check the released tables against the frozen split.",
    ),
    "sanitizer-residual": (
        "crackedpdfs_reanalysis.sanitizer_residual",
        "Measure what the sanitizer leaves per role.",
    ),
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: crackedpdfs-reanalysis <command> [options]\n")
        for name, (_, help_text) in COMMANDS.items():
            print(f"  {name:20s} {help_text}")
        return 0
    command, rest = args[0], args[1:]
    if command not in COMMANDS:
        print(f"unknown command {command!r}; choose from {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    import importlib

    module = importlib.import_module(COMMANDS[command][0])
    return int(module.main(rest))


if __name__ == "__main__":
    raise SystemExit(main())

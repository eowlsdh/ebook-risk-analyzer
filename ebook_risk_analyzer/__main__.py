"""Module entry point for ``python -m ebook_risk_analyzer``."""

from __future__ import annotations

import sys
from typing import Sequence

from .cli import main as cli_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, or launch the local browser UI with the ``web`` command."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    is_gui_bundle = (
        not arguments
        and bool(getattr(sys, "frozen", False))
        and sys.executable.casefold().endswith("ebookriskanalyzer.exe")
    )
    if arguments[:1] == ["web"] or is_gui_bundle:
        from .web_app import main as web_main

        return web_main(arguments[1:])
    return cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())

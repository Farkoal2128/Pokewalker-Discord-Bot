"""CLI entry point; operations and argument validation live in the adapter."""

import logging

from pokewalker.bot.client import main


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())

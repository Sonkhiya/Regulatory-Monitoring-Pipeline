"""Entry point for ``python -m regmon``."""

import sys

from regmon.cli import main

if __name__ == "__main__":
    sys.exit(main())

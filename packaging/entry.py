"""Entry point for the standalone PyInstaller build (see .github/workflows/release.yml)."""

import sys

from mocktcl.cli import main

sys.exit(main())

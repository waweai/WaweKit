"""Enable ``python -m wawekit`` as a launch entry point.

Keeping this file tiny is intentional: it only forwards to :func:`wawekit.app.run`,
which is the single *composition root* where the application is assembled. This
mirrors how large Python applications separate "how we are invoked" from "how we
are wired together".
"""

from __future__ import annotations

import sys

from wawekit.app import run

if __name__ == "__main__":
    sys.exit(run())

"""Entry point: ``python -m baton``."""

from __future__ import annotations

import logging
import sys

import uvicorn

from baton.app import create_app
from baton.config import ConfigError, load_config
from baton.logs import harden_logging


def main() -> int:
    """Start the server, refusing to run with an incomplete configuration."""
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"baton: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=config.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s"
    )
    harden_logging()
    uvicorn.run(
        create_app(config),
        host=config.listen_host,
        port=config.listen_port,
        log_level=config.log_level,
        proxy_headers=False,
        server_header=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

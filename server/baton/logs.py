"""Log hygiene: no listening history and no OAuth codes in the logs."""

from __future__ import annotations

import logging

QUIET_LOGGERS = ("httpx", "httpcore")


class StripQuery(logging.Filter):
    """Cut the query string from uvicorn access log lines (the callback carries code and state)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = args[2].partition("?")[0]
            record.args = tuple(args)
        return True


def harden_logging() -> None:
    """Keep request URLs of Spotify calls and access log query strings out of the logs."""
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").addFilter(StripQuery())

"""
UUID v7 generator — requires Python 3.14+ (uuid.uuid7 added in PEP 770).

UUID v7 encodes the current Unix timestamp (ms) in the high 48 bits, so
generated IDs sort to the rightmost B-tree leaf on every insert instead of
landing at a random position. This eliminates index page splits and
fragmentation under write load — critical for the high-volume events table.
"""

from uuid import uuid7 as new_uuid  # noqa: F401

__all__ = ["new_uuid"]

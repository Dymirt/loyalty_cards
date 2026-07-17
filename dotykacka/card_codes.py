"""Deprecated compatibility imports for :mod:`cards.codes`."""

from cards.codes import *  # noqa: F401,F403
from cards.codes import (
    CardCode,
    CardCodeError,
    LEGACY_CARD_NUMBER_MAX,
    LEGACY_CARD_PREFIX,
    card_number,
    normalize_card_code,
    parse_card_code,
)


__all__ = [
    "CardCode",
    "CardCodeError",
    "LEGACY_CARD_NUMBER_MAX",
    "LEGACY_CARD_PREFIX",
    "card_number",
    "normalize_card_code",
    "parse_card_code",
]

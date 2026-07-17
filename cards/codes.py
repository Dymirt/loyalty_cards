"""Parsing and normalization for physical loyalty-card codes."""

from dataclasses import dataclass
import re


LEGACY_CARD_PREFIX = "MB"
LEGACY_CARD_NUMBER_MAX = 999
_CARD_CODE_RE = re.compile(r"(?P<prefix>[A-Z][A-Z0-9]{0,9})-(?P<number>[1-9][0-9]*)\Z")


class CardCodeError(ValueError):
    pass


@dataclass(frozen=True)
class CardCode:
    prefix: str
    number: int

    @property
    def value(self) -> str:
        return f"{self.prefix}-{self.number}"


def parse_card_code(raw_value, *, expected_prefix=LEGACY_CARD_PREFIX, max_number=LEGACY_CARD_NUMBER_MAX):
    value = str(raw_value or "").strip().upper()
    match = _CARD_CODE_RE.fullmatch(value)
    if not match:
        raise CardCodeError("Card code must use the MB-123 format.")
    prefix = match.group("prefix")
    if prefix != expected_prefix.upper():
        raise CardCodeError(f"Card code must use the {expected_prefix.upper()} prefix.")
    number = int(match.group("number"))
    if number > max_number:
        raise CardCodeError(f"Card number must be between 1 and {max_number}.")
    return CardCode(prefix=prefix, number=number)


def normalize_card_code(raw_value):
    return parse_card_code(raw_value).value


def card_number(raw_value):
    return parse_card_code(raw_value).number

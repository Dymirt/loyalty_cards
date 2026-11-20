"""Stable numbering rules for virtual cards and their reusable artwork."""


VIRTUAL_CARD_FIRST_NUMBER = 601
VIRTUAL_CARD_ARTWORK_COUNT = 600


def virtual_artwork_source_number(virtual_number):
    if virtual_number < VIRTUAL_CARD_FIRST_NUMBER:
        raise ValueError("Virtual card numbers must start at 601.")
    return ((virtual_number - VIRTUAL_CARD_FIRST_NUMBER) % VIRTUAL_CARD_ARTWORK_COUNT) + 1


__all__ = [
    "VIRTUAL_CARD_ARTWORK_COUNT",
    "VIRTUAL_CARD_FIRST_NUMBER",
    "virtual_artwork_source_number",
]

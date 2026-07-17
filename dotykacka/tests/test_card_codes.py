from django.test import SimpleTestCase

from dotykacka.card_codes import (
    CardCodeError,
    card_number,
    normalize_card_code,
    parse_card_code,
)


class CardCodeTests(SimpleTestCase):
    def test_normalizes_whitespace_and_case(self):
        self.assertEqual(normalize_card_code("  mb-12 "), "MB-12")
        self.assertEqual(card_number("MB-12"), 12)

    def test_returns_structured_code(self):
        parsed = parse_card_code("MB-600")
        self.assertEqual(parsed.prefix, "MB")
        self.assertEqual(parsed.number, 600)
        self.assertEqual(parsed.value, "MB-600")

    def test_rejects_values_that_old_strip_logic_could_misread(self):
        invalid_values = (
            "MB-M",
            "MB-B",
            "MB-",
            "MB-0",
            "MB-001",
            "XX-12",
            "MB-12-extra",
            "MB-1000",
            "",
            None,
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(CardCodeError):
                parse_card_code(value)

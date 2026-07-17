from django.core.exceptions import ValidationError
from django.test import TestCase

from cards.codes import CardCodeError, parse_card_code
from cards.services import assign_locked_card, lock_available_card
from dotykacka.tests.base import create_klient, create_physical_card, create_tenant


class CardDomainTests(TestCase):
    def test_code_parser_is_owned_by_cards_and_tenant_prefix_is_explicit(self):
        self.assertEqual(parse_card_code(" sc-12 ", expected_prefix="SC").value, "SC-12")
        with self.assertRaises(CardCodeError):
            parse_card_code("MB-12", expected_prefix="SC")

    def test_inventory_service_rejects_cross_tenant_assignment(self):
        first = create_tenant()
        second = create_tenant(name="Other", slug="other", card_prefix="OT")
        card = create_physical_card(first, number=12)
        customer = create_klient("OT-12", tenant=second)

        locked = lock_available_card(tenant=first, code=card.code)
        with self.assertRaises(ValidationError):
            assign_locked_card(card=locked, customer=customer)

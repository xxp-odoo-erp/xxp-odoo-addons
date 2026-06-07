# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo.exceptions import ValidationError

from ..const import SERVICE_VALUE_ERRORS
from .common import CdekDeliveryTestCommon


class TestSaleOrderCdekService(CdekDeliveryTestCommon):
    """Tests for ``sale.order.cdek.service`` validation, compute, and write behavior."""

    def test_check_value_counter_positive_and_negative(self):
        """Verify counter services accept positive values and reject zero."""
        product = self._create_service_product("counter")
        line = self._create_service_line(product, counter_value=1)
        line._check_value()

        with self.assertRaises(ValidationError) as ctx:
            line.counter_value = 0
        self.assertIn(
            SERVICE_VALUE_ERRORS["counter"],
            str(ctx.exception),
            "Errors must be the same",
        )

    def test_check_value_price_positive_and_negative(self):
        """Verify price services accept positive values and reject zero."""
        product = self._create_service_product("price")
        line = self._create_service_line(product, price_value=10.0)
        line._check_value()

        with self.assertRaises(ValidationError) as ctx:
            line.price_value = 0.0
        self.assertIn(
            SERVICE_VALUE_ERRORS["price"], str(ctx.exception), "Errors must be the same"
        )

    def test_check_value_length_positive_and_negative(self):
        """Verify length services accept positive values and reject zero."""
        product = self._create_service_product("length")
        line = self._create_service_line(product, length_value=5.0)
        line._check_value()

        with self.assertRaises(ValidationError) as ctx:
            line.length_value = 0.0
        self.assertIn(
            SERVICE_VALUE_ERRORS["length"],
            str(ctx.exception),
            "Errors must be the same",
        )

    def test_check_value_phone_positive_and_negative(self):
        """Verify phone services accept non-empty values and reject empty strings."""
        product = self._create_service_product("phone")

        line = self._create_service_line(product, phone_value="+7 999 000 00 00")
        line._check_value()

        with self.assertRaises(ValidationError) as ctx:
            line.phone_value = ""
        self.assertIn(
            SERVICE_VALUE_ERRORS["phone"], str(ctx.exception), "Errors must be the same"
        )

    def test_compute_value_sets_correct_field(self):
        """
        Verify ``_compute_value`` exposes the typed field
        matching each reference type.
        """
        counter_product = self._create_service_product("counter")
        counter_line = self._create_service_line(counter_product, counter_value=3)
        counter_line._compute_value()
        self.assertEqual(counter_line.value, "3", "Value must be equal to 3")

        price_product = self._create_service_product("price")
        price_line = self._create_service_line(price_product, price_value=12.5)
        price_line._compute_value()
        self.assertEqual(price_line.value, "12.5", "Value must be equal to 12.5")

        length_product = self._create_service_product("length")
        length_line = self._create_service_line(length_product, length_value=7.0)
        length_line._compute_value()
        self.assertEqual(length_line.value, "7.0", "Value must be equal to 7.0")

        phone_product = self._create_service_product("phone")
        phone_line = self._create_service_line(
            phone_product, phone_value="+7 900 000 00 00"
        )
        phone_line._compute_value()
        self.assertEqual(
            phone_line.value,
            "+7 900 000 00 00",
            "Value must be equal to +7 900 000 00 00",
        )

    def test_compute_value_empty_for_unknown_type(self):
        """
        Verify ``_compute_value`` returns an empty string
        for unknown reference types.
        """
        product = self._create_service_product("unknown")
        line = self._create_service_line(product)
        line._compute_value()
        self.assertEqual(line.value, "", "Value must be empty")

    def test_write_unlink_when_order_id_set_to_false(self):
        """Verify writing ``order_id=False`` unlinks the service line."""
        product = self._create_service_product("counter")
        line = self._create_service_line(product, counter_value=1)
        line_id = line.id

        result = line.write({"order_id": False})

        self.assertTrue(result)
        self.assertFalse(
            self.env["sale.order.cdek.service"].browse(line_id).exists(),
            "Line must be deleted",
        )

# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from types import SimpleNamespace

from odoo.exceptions import ValidationError

from .common import CdekDeliveryTestCommon


class TestCdekTariffMode(CdekDeliveryTestCommon):
    """Tests for ``cdek.tariff.mode`` compute fields and package validation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tariff, cls.mode = cls.create_cdek_tariff_and_mode(
            weight_min=1.0,
            weight_max=10.0,
            weight_calc_max=8.0,
            length_min=10,
            length_max=50,
            width_min=5,
            width_max=40,
            height_min=2,
            height_max=30,
        )

    def test_compute_dimensions(self):
        """
        Verify ``dimensions`` is built from
        the parent tariff max LxWxH and weight.
        """
        self.mode._compute_dimensions()
        self.assertEqual(
            self.mode.dimensions,
            "50x40x30 cm 10.0 kg",
            "dimensions should match tariff max LxWxH and weight_max",
        )

    def test_compute_display_name(self):
        """Verify ``display_name`` follows ``[code] tariff name - mode name``."""
        self.mode._compute_display_name()
        expected = f"[{self.mode.code}] {self.tariff.name} - {self.mode.name}"
        self.assertEqual(
            self.mode.display_name,
            expected,
            "display_name should follow [code] tariff - mode format",
        )

    def test_check_package_tariff_positive(self):
        """Verify a package within tariff limits passes validation."""
        package = self.make_delivery_package(
            weight=5.0,
            package_type=self.env["stock.package.type"].create(
                {
                    "name": "Test package",
                    "packaging_length": 20,
                    "width": 10,
                    "height": 10,
                }
            ),
        )
        self.mode._check_package_tariff([package])

    def test_check_package_tariff_invalid_size(self):
        """Verify oversize packages raise ``ValidationError``."""
        package = self.make_delivery_package(
            weight=5.0,
            package_type=self.env["stock.package.type"].create(
                {
                    "name": "Too long package",
                    "packaging_length": 1000,
                    "width": 10,
                    "height": 10,
                }
            ),
        )
        with self.assertRaises(ValidationError):
            self.mode._check_package_tariff([package])

    def test_check_package_tariff_invalid_weight(self):
        """Verify packages above ``weight_max`` raise ``ValidationError``."""
        package = self.make_delivery_package(
            weight=20.0,
            package_type=self.env["stock.package.type"].create(
                {
                    "name": "Heavy package",
                    "packaging_length": 20,
                    "width": 10,
                    "height": 10,
                }
            ),
        )
        with self.assertRaises(ValidationError):
            self.mode._check_package_tariff([package])

    def test_check_package_tariff_invalid_weight_calc(self):
        """Verify packages above ``weight_calc_max`` raise ``ValidationError``."""
        package = self.make_delivery_package(
            weight=9.0,
            package_type=self.env["stock.package.type"].create(
                {
                    "name": "Too calc heavy",
                    "packaging_length": 20,
                    "width": 10,
                    "height": 10,
                }
            ),
        )
        with self.assertRaises(ValidationError):
            self.mode._check_package_tariff([package])

    def test_get_or_create_creates_new_modes_and_skips_existing(self):
        """Verify ``get_or_create`` skips existing codes and returns new modes only."""
        DeliveryModeLike = SimpleNamespace
        existing_code = self.mode.code

        delivery_modes = [
            DeliveryModeLike(
                tariff_code=existing_code,
                delivery_mode="1",
                delivery_mode_name="Existing mode",
            ),
            DeliveryModeLike(
                tariff_code=9999,
                delivery_mode="1",
                delivery_mode_name="New mode",
            ),
        ]

        before_ids = set(self.env["cdek.tariff.mode"].search([]).ids)
        created = self.env["cdek.tariff.mode"].get_or_create(
            self.tariff.id, delivery_modes
        )
        after_records = self.env["cdek.tariff.mode"].search([])
        after_ids = set(after_records.ids)

        self.assertEqual(
            len(created),
            1,
            "only one new mode should be created (existing skipped)",
        )
        self.assertIn(
            "New mode",
            created.mapped("name"),
            "created record should be the new mode",
        )
        self.assertEqual(
            after_ids - before_ids,
            set(created.ids),
            "new DB ids should match created recordset",
        )

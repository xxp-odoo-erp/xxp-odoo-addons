# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from types import SimpleNamespace

from .common import CdekDeliveryTestCommon


class TestCdekTariff(CdekDeliveryTestCommon):
    """Tests for ``cdek.tariff`` limit checks and API sync via ``get_or_create``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tariff, _mode = cls.create_cdek_tariff_and_mode(
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

    def test_check_size_positive(self):
        """Verify ``_check_size`` accepts dimensions at min and max bounds."""
        self.assertTrue(
            self.tariff._check_size(length=10, width=5, height=2),
            "min dimensions should be valid",
        )
        self.assertTrue(
            self.tariff._check_size(length=50, width=40, height=30),
            "max dimensions should be valid",
        )

    def test_check_size_negative_length(self):
        """Verify ``_check_size`` rejects length below min or above max."""
        self.assertFalse(
            self.tariff._check_size(length=9, width=10, height=10),
            "length below min should be invalid",
        )
        self.assertFalse(
            self.tariff._check_size(length=51, width=10, height=10),
            "length above max should be invalid",
        )

    def test_check_size_negative_width(self):
        """Verify ``_check_size`` rejects width below min or above max."""
        self.assertFalse(
            self.tariff._check_size(length=20, width=4, height=10),
            "width below min should be invalid",
        )
        self.assertFalse(
            self.tariff._check_size(length=20, width=41, height=10),
            "width above max should be invalid",
        )

    def test_check_size_negative_height(self):
        """Verify ``_check_size`` rejects height below min or above max."""
        self.assertFalse(
            self.tariff._check_size(length=20, width=10, height=1),
            "height below min should be invalid",
        )
        self.assertFalse(
            self.tariff._check_size(length=20, width=10, height=31),
            "height above max should be invalid",
        )

    def test_check_weight_positive(self):
        """Verify ``_check_weight`` accepts weight at min and max bounds."""
        self.assertTrue(
            self.tariff._check_weight(1.0),
            "weight at min should be valid",
        )
        self.assertTrue(
            self.tariff._check_weight(10.0),
            "weight at max should be valid",
        )

    def test_check_weight_negative(self):
        """Verify ``_check_weight`` rejects weight below min or above max."""
        self.assertFalse(
            self.tariff._check_weight(0.9),
            "weight below min should be invalid",
        )
        self.assertFalse(
            self.tariff._check_weight(10.1),
            "weight above max should be invalid",
        )

    def test_check_weight_calc_positive(self):
        """Verify ``_check_weight_calc`` accepts weight up to ``weight_calc_max``."""
        self.assertTrue(
            self.tariff._check_weight_calc(1.0),
            "weight at min should be valid for calc",
        )
        self.assertTrue(
            self.tariff._check_weight_calc(8.0),
            "weight at weight_calc_max should be valid",
        )

    def test_check_weight_calc_negative(self):
        """Verify ``_check_weight_calc`` rejects weight above ``weight_calc_max``."""
        self.assertFalse(
            self.tariff._check_weight_calc(8.1),
            "weight above weight_calc_max should be invalid",
        )

    def test_get_or_create_creates_new_tariffs_and_modes(self):
        """
        Verify ``get_or_create`` creates tariffs
        and modes from an API-like payload.
        """
        TariffLike = SimpleNamespace
        ModeLike = SimpleNamespace
        tariffs_result = [
            TariffLike(
                tariff_name="Tariff A",
                weight_min=0.0,
                weight_max=5.0,
                weight_calc_max=4.0,
                length_min=10,
                length_max=20,
                width_min=10,
                width_max=20,
                height_min=5,
                height_max=15,
                delivery_modes=[
                    ModeLike(
                        tariff_code=101,
                        delivery_mode=1,
                        delivery_mode_name="Door-Door",
                    )
                ],
            ),
            TariffLike(
                tariff_name="Tariff B",
                weight_min=1.0,
                weight_max=10.0,
                weight_calc_max=8.0,
                length_min=15,
                length_max=25,
                width_min=15,
                width_max=25,
                height_min=10,
                height_max=20,
                delivery_modes=[
                    ModeLike(
                        tariff_code=102,
                        delivery_mode=1,
                        delivery_mode_name="Door-Door B",
                    )
                ],
            ),
        ]

        created = self.env["cdek.tariff"].get_or_create(tariffs_result)

        self.assertEqual(
            len(created),
            2,
            "should create two tariff records",
        )
        names = set(created.mapped("name"))
        self.assertEqual(
            names,
            {"Tariff A", "Tariff B"},
            "created tariffs should have expected names",
        )

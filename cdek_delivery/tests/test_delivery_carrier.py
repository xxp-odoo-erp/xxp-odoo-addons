# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from types import SimpleNamespace

from odoo.exceptions import UserError

from .common import CdekDeliveryTestCommon, FakeCdekRequest


class TestDeliveryCarrier(CdekDeliveryTestCommon):
    """Tests for CDEK ``delivery.carrier`` integration.

    Covers compute flags, API client wiring, rate/shipping flows, tracking,
    cancellation, and tariff synchronization.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.carrier = cls.create_cdek_carrier()

    def test_compute_can_generate_return_for_cdek(self):
        """Verify CDEK carriers enable return label generation."""
        self.carrier._compute_can_generate_return()
        self.assertTrue(
            self.carrier.can_generate_return,
            "CDEK carrier should support returns",
        )

    def test_compute_supports_shipping_insurance_for_cdek(self):
        """Verify CDEK carriers enable shipping insurance support."""
        self.carrier._compute_supports_shipping_insurance()
        self.assertTrue(
            self.carrier.supports_shipping_insurance,
            "CDEK carrier should support shipping insurance",
        )

    def test_cdek_request_no_carer(self):
        """Verify ``_cdek_request`` raises ``UserError`` on an empty recordset."""
        Carrier = self.env["delivery.carrier"]
        with self.assertRaises(UserError):
            Carrier.browse()._cdek_request()

    def test_cdek_request_no_cdek_type(self):
        """Verify ``_cdek_request`` raises ``UserError`` for non-CDEK carriers."""
        other_carrier = self.env["delivery.carrier"].create(
            {
                "name": "Other",
                "delivery_type": "fixed",
                "fixed_price": 0.0,
                "product_id": self.env["product.product"]
                .create({"name": "Delivery Product 2"})
                .id,
            }
        )
        with self.assertRaises(UserError):
            other_carrier._cdek_request()

    def test_cdek_request_returns_cdek_request(self):
        """Verify ``_cdek_request`` returns the patched ``CdekRequest`` instance."""
        mocked, fake_request = self.patch_cdek_request(self.carrier)
        result = self.carrier._cdek_request()
        self.assertIs(
            result,
            fake_request,
            "Expected _cdek_request to return the patched fake",
        )
        mocked.assert_called_once()

    def test_convert_to_grams(self):
        """Verify ``convert_to_grams`` converts 1 kg to 1000 g."""
        uom_kg = self.env.ref("uom.product_uom_kgm")
        grams = self.carrier.convert_to_grams(1.0, uom_kg)
        self.assertEqual(grams, 1000.0, "1 kg should equal 1000 g")

    def test_rate_params_basic(self):
        """Verify ``_rate_params`` builds the rate hook response dictionary."""
        params = self.carrier._rate_params(
            success=True, price=100.0, services={"a": 1}, error_message=None
        )
        self.assertTrue(params["success"], "success should be True")
        self.assertEqual(params["price"], 100.0, "price should be 100.0")
        self.assertIn("services", params, "services key should be present")

    def test_cdek_rate_shipment_no_partner_shipping(self):
        """Verify ``cdek_rate_shipment`` fails when no delivery address is set."""
        order = self.create_sale_order_with_cdek_services()
        order.partner_shipping_id = False
        res = self.carrier.cdek_rate_shipment(order)
        self.assertFalse(res["success"], "rate should fail without shipping address")
        self.assertIn(
            "Delivery address not specified",
            res["error_message"],
            "error message should mention missing delivery address",
        )

    def test_cdek_rate_shipment_no_tariff_for_partner(self):
        """Verify ``cdek_rate_shipment`` fails when the partner has no tariff mode."""
        order = self.create_sale_order_with_cdek_services()
        mocked, fake_request = self.patch_cdek_request(self.carrier)
        res = self.carrier.cdek_rate_shipment(order)
        self.assertFalse(res["success"], "rate should fail without partner tariff")
        self.assertIn(
            "CDEK: Tariff is not set for partner",
            res["error_message"],
            "error message should mention tariff not set",
        )
        mocked.assert_called_once()

    def test_cdek_rate_shipment_success(self):
        """Verify ``cdek_rate_shipment`` quotes price and fills service totals."""
        order = self.create_sale_order_with_cdek_services()
        tariff, mode = self.create_cdek_tariff_and_mode()
        order.partner_shipping_id = self.create_partner_with_cdek(
            cdek_tariff_mode_id=mode.id
        )

        tariff_response = SimpleNamespace(
            total_sum=500.0,
            services=[
                SimpleNamespace(code=s.product_id.cdek_reference, total_sum=50)
                for s in order.cdek_service_ids
            ],
        )
        fake_request = FakeCdekRequest(
            self.carrier,
            tariff_calc_result=tariff_response,
        )
        mocked, _ = self.patch_cdek_request(self.carrier, fake_request=fake_request)

        res = self.carrier.cdek_rate_shipment(order)

        self.assertTrue(res["success"], "rate should succeed with tariff and mock")
        self.assertEqual(res["price"], 500.0, "price should match mock total_sum")
        for service in order.cdek_service_ids:
            self.assertEqual(
                service.total_price,
                50,
                "each service total_price should match mock",
            )
        mocked.assert_called_once()

    def test_create_error_message(self):
        """Verify ``_create_error_message`` joins API errors or returns falsy."""
        Error = SimpleNamespace
        RequestLike = SimpleNamespace
        requests_ = [
            RequestLike(errors=[Error(message="err1"), Error(message="err2")]),
            RequestLike(errors=[Error(message="err3")]),
        ]
        msg = self.carrier._create_error_message(requests_)
        self.assertEqual(
            msg,
            "err1\nerr2\nerr3",
            "error messages should be joined by newline",
        )

        empty_msg = self.carrier._create_error_message([RequestLike(errors=None)])
        self.assertFalse(empty_msg, "no errors should yield falsy message")

    def test_cdek_send_shipping_no_tariff_for_partner(self):
        """
        Verify ``cdek_send_shipping`` raises
        ``UserError`` when picking weight is zero.
        """
        order = self.create_sale_order_with_cdek_services()
        picking = self.create_picking_from_order(order)
        with self.assertRaises(UserError) as ctx:
            self.carrier.cdek_send_shipping(picking)
        self.assertIn(
            "The package cannot be created because the total weight "
            "of the products in the picking is 0.0",
            str(ctx.exception),
            "exception should mention zero weight",
        )

    def test_cdek_get_tracking_link(self):
        """
        Verify ``cdek_get_tracking_link``
        embeds ``carrier_tracking_ref`` in the URL.
        """
        picking = self.env["stock.picking"].new({})
        picking.carrier_tracking_ref = "ABC123"
        url = self.carrier.cdek_get_tracking_link(picking)
        self.assertIn("ABC123", url, "tracking ref should appear in URL")

    def test_cdek_cancel_shipment(self):
        """
        Verify ``cdek_cancel_shipment`` clears CDEK
        and tracking fields on pickings.
        """
        order = self.create_sale_order_with_cdek_services()
        _, mode = self.create_cdek_tariff_and_mode()
        partner = self.create_partner_with_cdek(cdek_tariff_mode_id=mode.id)
        order.partner_shipping_id = partner
        picking = self.create_picking_from_order(order)
        picking.cdek_order_uuid = "uuid-123"
        picking.carrier_tracking_ref = "TRACK123"

        fake_request = FakeCdekRequest(
            self.carrier,
            order_refusal=SimpleNamespace(),
        )
        mocked, _ = self.patch_cdek_request(self.carrier, fake_request=fake_request)

        self.carrier.cdek_cancel_shipment(picking)

        self.assertEqual(
            picking.carrier_tracking_ref,
            "",
            "tracking ref should be cleared after cancel",
        )
        self.assertEqual(
            picking.carrier_price,
            0.0,
            "carrier price should be cleared after cancel",
        )
        self.assertFalse(
            picking.cdek_order_uuid,
            "cdek_order_uuid should be cleared after cancel",
        )
        mocked.assert_called_once()

    def test_action_upload_cdek_tariffs_calls_get_tariffs_and_get_or_create(self):
        """
        Verify ``action_upload_cdek_tariffs``
        syncs tariffs and shows a notification.
        """
        ModeLike = SimpleNamespace
        TariffLike = SimpleNamespace
        fake_tariffs_result = [
            TariffLike(
                tariff_name="T1",
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
                        tariff_code=201,
                        delivery_mode=1,
                        delivery_mode_name="Door-Door",
                    )
                ],
            )
        ]

        fake_request = FakeCdekRequest(self.carrier)
        fake_request.get_tariffs = lambda: fake_tariffs_result

        mocked_request, _ = self.patch_cdek_request(
            self.carrier, fake_request=fake_request
        )

        action = self.carrier.action_upload_cdek_tariffs()
        mocked_request.assert_called_once()
        self.assertEqual(
            action["type"],
            "ir.actions.client",
            "action should be client notification",
        )
        self.assertEqual(
            action["tag"],
            "display_notification",
            "action tag should be display_notification",
        )
        params = action.get("params", {})
        self.assertEqual(
            params.get("type"),
            "success",
            "notification type should be success",
        )
        self.assertIn(
            "Tariffs loaded",
            params.get("title", ""),
            "title should mention tariffs loaded",
        )
        self.assertIn(
            "CDEK tariffs have been synchronized",
            params.get("message", ""),
            "message should mention CDEK sync",
        )

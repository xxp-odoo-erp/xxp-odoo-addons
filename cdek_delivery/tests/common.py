# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.delivery.models.delivery_request_objects import DeliveryPackage

from ..tools.cdek_request import CdekRequest


class FakeCdekTariffComponent:
    """Stand-in for ``client.tariff`` in unit tests."""

    def __init__(self, calc_result=None, tariffs_result=None):
        """Configure return values for ``calc()`` and ``all()`` / ``get_codes()``.

        Args:
            calc_result: Object returned by ``calc()``.
            tariffs_result: Tariffs used by ``all()`` and ``get_codes()``.
        """
        self._calc_result = calc_result
        self._tariffs_result = tariffs_result or []

    def calc(self, *args, **kwargs):
        return self._calc_result

    def all(self):
        codes = [t.tariff_code for t in self._tariffs_result]
        return SimpleNamespace(get_codes=lambda *_, **__: codes)


class FakeCdekOrderComponent:
    """Stand-in for ``client.order`` in unit tests."""

    def __init__(
        self,
        create_result=None,
        get_result=None,
        refusal_result=None,
        delete_result=None,
    ):
        """Configure return values for order API calls.

        Args:
            create_result: Value returned by ``create()``.
            get_result: Value returned by ``get_by_uuid()``.
            refusal_result: Value returned by ``refusal()``.
            delete_result: Value returned by ``delete()``.
        """
        self._create_result = create_result
        self._get_result = get_result
        self._refusal_result = refusal_result
        self._delete_result = delete_result

    def create(self, *args, **kwargs):  # pylint: disable=method-required-super
        return self._create_result

    def get_by_uuid(self, *args, **kwargs):
        return self._get_result

    def refusal(self, *args, **kwargs):
        return self._refusal_result

    def delete(self, *args, **kwargs):
        return self._delete_result


class FakeCdekOfficeComponent:
    """Stand-in for ``client.office`` in unit tests."""

    def __init__(self, offices=None):
        """Configure the list returned by ``_get_offices()``.

        Args:
            offices: Office records to return; defaults to an empty list.
        """
        self._offices = offices or []

    def _get_offices(self, *args, **kwargs):
        return self._offices


class FakeCdekLocationComponent:
    """Stand-in for ``client.location`` in unit tests."""

    def __init__(self, cities=None):
        """Configure the list returned by ``cities()``.

        Args:
            cities: City records to return; defaults to an empty list.
        """
        self._cities = cities or []

    def cities(self, *args, **kwargs):
        return self._cities


class FakeCdekCurrencyComponent:
    """Stand-in for ``client.currency`` used in tariff calculation."""

    def get(self, name):
        """Return a fixed currency code for any currency name.

        Args:
            name: Currency name (for example from ``res.currency``).

        Returns:
            int: Constant code ``1`` used in API requests.
        """
        return 1


class FakeCdekClient:
    """In-memory CDEK client assembled from fake API components."""

    def __init__(
        self,
        tariff_calc_result=None,
        tariffs_result=None,
        order_create=None,
        order_get=None,
        order_refusal=None,
        order_delete=None,
        offices=None,
        cities=None,
    ):
        """Build a fake client with configurable component responses.

        Args:
            tariff_calc_result: Result of ``tariff.calc()``.
            tariffs_result: Tariff list for ``tariff.all()`` / ``get_tariffs``.
            order_create: Result of ``order.create()``.
            order_get: Result of ``order.get_by_uuid()``.
            order_refusal: Result of ``order.refusal()``.
            order_delete: Result of ``order.delete()``.
            offices: Offices returned by ``office._get_offices()``.
            cities: Cities returned by ``location.cities()``.
        """
        self.tariff = FakeCdekTariffComponent(
            calc_result=tariff_calc_result,
            tariffs_result=tariffs_result,
        )
        self.order = FakeCdekOrderComponent(
            create_result=order_create,
            get_result=order_get,
            refusal_result=order_refusal,
            delete_result=order_delete,
        )
        self.office = FakeCdekOfficeComponent(offices=offices)
        self.location = FakeCdekLocationComponent(cities=cities)
        self.currency = FakeCdekCurrencyComponent()


class FakeCdekRequest(CdekRequest):
    """Test double for ``CdekRequest`` with a configurable in-memory client."""

    def __init__(
        self,
        carrier,
        client=None,
        tariff_calc_result=None,
        tariffs_result=None,
        order_create=None,
        order_get=None,
        order_refusal=None,
        order_delete=None,
        offices=None,
        cities=None,
    ):
        """Build a fake request and optionally stub ``calculate()`` results.

        Args:
            carrier: ``delivery.carrier`` record configured for CDEK.
            client: Optional pre-built fake client; otherwise built from kwargs.
            tariff_calc_result: When set, ``calculate()`` returns this value.
            tariffs_result: Tariff list for ``get_tariffs()``.
            order_create: Result stub for ``order.create()``.
            order_get: Result stub for ``order.get_by_uuid()``.
            order_refusal: Result stub for ``order.refusal()``.
            order_delete: Result stub for ``order.delete()``.
            offices: Offices for ``office._get_offices()``.
            cities: Cities for ``location.cities()``.
        """
        super().__init__(carrier)
        self._tariff_calc_result = tariff_calc_result
        self.client = client or FakeCdekClient(
            tariff_calc_result=tariff_calc_result,
            tariffs_result=tariffs_result,
            order_create=order_create,
            order_get=order_get,
            order_refusal=order_refusal,
            order_delete=order_delete,
            offices=offices,
            cities=cities,
        )

    def calculate(self, shipping_partner, sender, currency, packages, services):
        """Return a stubbed tariff result or delegate to the real implementation.

        Args:
            shipping_partner: ``res.partner`` delivery address.
            sender: ``res.partner`` sender address.
            currency: ``res.currency`` used for the calculation.
            packages: ``DeliveryPackage`` objects to ship.
            services: ``sale.order.cdek.service`` recordset.

        Returns:
            TariffResponse-like object when stubbed, otherwise the result of
            ``super().calculate()``.
        """
        if self._tariff_calc_result is not None:
            return self._tariff_calc_result
        return super().calculate(shipping_partner, sender, currency, packages, services)


class CdekDeliveryTestCommon(TransactionCase):
    """Shared fixtures and helpers for CDEK delivery module tests.

    Provides factory methods for carriers, tariffs, partners, orders, pickings,
    delivery packages, and a helper to patch ``CdekRequest``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Test partner",
                "street": "Street 1",
                "city": "City",
                "zip": "123456",
                "country_id": cls.env.ref("base.ru").id
                if cls.env.ref("base.ru", raise_if_not_found=False)
                else False,
            }
        )
        cls.order = cls.create_sale_order_with_cdek_services()

    @classmethod
    def create_cdek_carrier(cls, **vals):
        """Create a ``delivery.carrier`` with ``delivery_type`` set to CDEK.

        Args:
            **vals: Field overrides (name, ``cdek_type``, ``product_id``, etc.).

        Returns:
            recordset: Created ``delivery.carrier`` record.
        """
        carrier_vals = {
            "name": "CDEK Test",
            "delivery_type": "cdek",
            "cdek_type": "1",
            "product_id": cls.env["product.product"]
            .create({"name": "Delivery Product"})
            .id,
        }
        carrier_vals.update(vals)
        return cls.env["delivery.carrier"].create(carrier_vals)

    @classmethod
    def create_cdek_tariff_and_mode(cls, **vals):
        """Create a ``cdek.tariff`` and a related ``cdek.tariff.mode``.

        Args:
            **vals: Field overrides applied to the tariff record.

        Returns:
            tuple: ``(cdek.tariff, cdek.tariff.mode)`` records.
        """
        tariff_vals = {
            "name": "Tariff Test",
            "weight_min": 0.0,
            "weight_max": 100.0,
            "weight_calc_max": 100.0,
            "length_min": 0,
            "length_max": 100,
            "width_min": 0,
            "width_max": 100,
            "height_min": 0,
            "height_max": 100,
        }
        tariff_vals.update(vals)
        tariff = cls.env["cdek.tariff"].create(tariff_vals)
        mode = cls.env["cdek.tariff.mode"].create(
            {
                "tariff_id": tariff.id,
                "name": "Mode Test",
                "mode": "1",
                "code": 1,
                "delivery_from": "door",
                "delivery_to": "door",
            }
        )
        return tariff, mode

    @classmethod
    def create_partner_with_cdek(cls, **vals):
        """Create a ``res.partner`` with a default delivery address.

        Args:
            **vals: Extra fields (for example ``cdek_tariff_mode_id``, name, city).

        Returns:
            recordset: Created ``res.partner`` record.
        """
        partner_vals = {
            "name": "CDEK Partner",
            "street": "Street 1",
            "city": "City",
            "zip": "123456",
        }
        partner_vals.update(vals)
        return cls.env["res.partner"].create(partner_vals)

    @classmethod
    def create_sale_order_with_cdek_services(cls, partner=None, carrier=None, **vals):
        """Create a ``sale.order`` with one product line (not confirmed).

        Args:
            partner: ``res.partner`` for the order; defaults to ``cls.partner``.
            carrier: ``delivery.carrier``; defaults to ``create_cdek_carrier()``.
            **vals: Extra order field values.

        Returns:
            recordset: Created ``sale.order`` record.
        """
        if not partner:
            partner = cls.partner
        if not carrier:
            carrier = cls.create_cdek_carrier()
        order_vals = {
            "partner_id": partner.id,
            "carrier_id": carrier.id,
        }
        order_vals.update(vals)
        order = cls.env["sale.order"].create(order_vals)

        product = cls.env["product.product"].create(
            {
                "name": "Test Product",
                "type": "product",
                "weight": 1.0,
            }
        )
        cls.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "product_id": product.id,
                "product_uom_qty": 1.0,
                "price_unit": 100.0,
            }
        )
        return order

    def create_picking_from_order(self, order):
        """Confirm a sales order and return its first picking.

        Args:
            order: ``sale.order`` to confirm.

        Returns:
            recordset: First ``stock.picking`` of the order.

        Raises:
            AssertionError: If the order has no pickings after confirmation.
        """
        order.action_confirm()
        pickings = order.picking_ids
        self.assertTrue(
            pickings, "order should have at least one picking after confirm"
        )
        return pickings[0]

    def make_delivery_package(self, weight, package_type, commodities=None, **kwargs):
        """Build a ``DeliveryPackage`` instance for tariff validation tests.

        Args:
            weight: Package weight.
            package_type: ``stock.package.type`` record.
            commodities: Optional commodity list; defaults to ``[]``.
            **kwargs: Extra keyword arguments passed to ``DeliveryPackage``.

        Returns:
            DeliveryPackage: Package object used by carrier rate/shipping code.
        """
        return DeliveryPackage(
            commodities=commodities or [],
            weight=weight,
            package_type=package_type,
            **kwargs,
        )

    def patch_cdek_request(self, carrier, fake_request=None):
        """Patch ``CdekRequest`` so ``_cdek_request`` returns a fake client.

        The patch is stopped automatically when the test ends.

        Args:
            carrier: ``delivery.carrier`` used to build ``FakeCdekRequest``.
            fake_request: Optional pre-built fake; otherwise created from ``carrier``.

        Returns:
            tuple: ``(mock patch object, FakeCdekRequest instance)``.
        """
        fake_request = fake_request or FakeCdekRequest(carrier)
        patcher = patch(
            "odoo.addons.cdek_delivery.models.delivery_carrier.CdekRequest",
            return_value=fake_request,
        )
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked, fake_request

    def _create_service_product(self, reference_type):
        """Get or create a CDEK service product for the given value type.

        Args:
            reference_type: One of ``counter``, ``price``, ``length``, ``phone``;
                any other value maps to ``ANOTHER``.

        Returns:
            recordset: ``product.product`` with ``cdek_reference`` set.
        """
        mapping = {
            "counter": "CARTON_BOX_XS",
            "price": "INSURANCE",
            "length": "BUBBLE_WRAP",
            "phone": "SMS",
        }
        cdek_reference = mapping.get(reference_type, "ANOTHER")
        Product = self.env["product.product"]
        product = Product.search([("cdek_reference", "=", cdek_reference)], limit=1)
        if not product:
            product = Product.create(
                {
                    "name": f"Service {reference_type}",
                    "type": "service",
                    "categ_id": self.env.ref("product.product_category_all").id,
                    "cdek_reference": cdek_reference,
                }
            )
        return product

    def _create_service_line(self, product, **vals):
        """Create a CDEK service line on ``self.order``.

        Args:
            product: ``product.product`` service with ``cdek_reference`` set.
            **vals: Extra field values for the service line.

        Returns:
            recordset: Created ``sale.order.cdek.service`` record.
        """
        return self.env["sale.order.cdek.service"].create(
            {
                "order_id": self.order.id,
                "product_id": product.id,
                **vals,
            }
        )

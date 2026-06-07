# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from cdek import CdekClient
from cdek.apps.location import CitiesResponse, CityListFilter
from cdek.apps.models import (
    AdditionalService,
    CalcPackage,
    Contact,
    EntityResponse,
    Money,
    OrderLocation,
    Package,
    Seller,
)
from cdek.apps.office import OfficeFilter, OfficeResponse
from cdek.apps.order import OrderEntityResponse, OrderRequest
from cdek.apps.tariff import CalcAdditionalService, TariffCodeRequest, TariffResponse

from odoo import _
from odoo.exceptions import UserError, ValidationError

from ..const import ORDER_TYPE


class CdekRequest:
    """Wrapper for CDEK API calls used by Odoo delivery carriers.

    Initializes a :class:`CdekClient` from the carrier credentials and
    exposes helpers to calculate tariffs, create and cancel orders,
    and query CDEK cities and pickup offices.

    Args:
        carrier: ``delivery.carrier`` record configured for CDEK delivery.
    """

    def __init__(self, carrier):
        super_carrier = carrier.sudo()
        self.carrier = super_carrier
        self.logger = super_carrier.log_xml
        if self.carrier.prod_environment:
            self.client = CdekClient(
                self.carrier.cdek_client_id,
                self.carrier.cdek_client_secret,
                timeout=10.0,
            )
        else:
            self.client = CdekClient("TEST", timeout=10.0)
        self.env = self.carrier.env
        self.order_type = str(self.carrier.cdek_type or "1")
        self.print_type = self.carrier.cdek_print_type or "WAYBILL"
        self.weight_uom = self.env[
            "product.template"
        ]._get_weight_uom_id_from_ir_config_parameter()

    def _set_order_packages(self, packages) -> list[CalcPackage]:
        """Convert delivery packages to CDEK tariff calculation payloads.

        Args:
            packages: Iterable of ``DeliveryPackage`` objects.

        Returns:
            list[CalcPackage]: Package weights and dimensions for the tariff API.
        """
        return [
            CalcPackage(
                weight=self.carrier.convert_to_grams(package.weight, self.weight_uom),
                length=package.dimension.get("length", self.carrier.default_length),
                width=package.dimension.get("width", self.carrier.default_width),
                height=package.dimension.get("height", self.carrier.default_height),
            )
            for package in packages
        ]

    def _get_calc_services(self, services) -> list[CalcAdditionalService] | None:
        """Build additional services for tariff calculation.

        Args:
            services: ``sale.order.cdek.service`` recordset.

        Returns:
            list[CalcAdditionalService] | None: CDEK service payloads, or
            ``None`` when no services are provided.
        """
        if not services:
            return None
        return [
            CalcAdditionalService(
                code=service.product_id.cdek_reference,
                parameter=service.value,
            )
            for service in services
        ]

    def _get_order_services(self, services) -> list[AdditionalService] | None:
        """Build additional services for order creation.

        Args:
            services: ``sale.order.cdek.service`` recordset.

        Returns:
            list[AdditionalService] | None: CDEK service payloads, or
            ``None`` when no services are provided.
        """
        if not services:
            return None
        return [
            AdditionalService(
                code=service.product_id.cdek_reference,
                parameter=service.value,
            )
            for service in services
        ]

    def _get_office_location(self, partner) -> dict:
        """Resolve CDEK office location data for a partner.

        Args:
            partner: ``res.partner`` record with office delivery settings.

        Returns:
            dict: Location fields expected by the CDEK API.

        Raises:
            ValidationError: If the office code is missing or not found.
        """
        if not partner.cdek_office_code:
            raise ValidationError(
                _("Office code is not set for partner %s", partner.display_name)
            )
        offices = self.client.office._get_offices(
            OfficeFilter(code=partner.cdek_office_code)  # pyright: ignore
        )
        if not offices:
            raise ValidationError(
                _("Office not found for partner %s", partner.display_name)
            )
        location = offices[0].location
        return {
            "code": location.code,
            "country_code": location.country_code,
            "city": location.city,
            "address": location.address,
            "postal_code": location.postal_code,
        }

    def _get_door_location(self, partner) -> dict:
        """Resolve CDEK door-delivery location data for a partner.

        Args:
            partner: ``res.partner`` record with a door delivery address.

        Returns:
            dict: Location fields expected by the CDEK API.

        Raises:
            ValidationError: If required address fields are missing.
        """
        if not (partner.country_code and partner.city and partner.street):
            raise ValidationError(
                _("Country code, city and street are required for door delivery")
            )
        cities = self.client.location.cities(
            filter_params=CityListFilter(  # pyright: ignore
                country_codes=partner.country_code,
                city=partner.city,
                postal_code=partner.zip or None,
                size=1,
            )
        )
        if cities:
            city = cities[0]
            return {
                "code": city.code,
                "country_code": city.country_code,
                "city": city.city,
                "address": partner.street,
            }
        return {
            "country_code": partner.country_code,
            "city": partner.city,
            "address": partner.street,
        }

    def _get_location(self, partner) -> dict:
        """Resolve CDEK location data based on the partner delivery type.

        Args:
            partner: ``res.partner`` record with CDEK delivery settings.

        Returns:
            dict: Office or door location fields for the CDEK API.

        Raises:
            ValidationError: If the delivery type is unsupported.
        """
        if partner.cdek_delivery_type in ("office", "postbox"):
            return self._get_office_location(partner)
        elif partner.cdek_delivery_type == "door":
            return self._get_door_location(partner)
        else:
            raise ValidationError(
                _("Invalid delivery type for partner %s", partner.display_name)
            ) from None

    def get_city_code(self, city, country_code, postal_code=None) -> CitiesResponse:
        """Look up a city in the CDEK location API.

        Args:
            city: City name.
            country_code: ISO country code.
            postal_code: Optional postal code to narrow the search.

        Returns:
            CitiesResponse: Matching city returned by CDEK.

        Raises:
            ValidationError: If required fields are missing or the city is not found.
        """
        if not city or not country_code:
            raise ValidationError(_("City and country code are required")) from None
        cities = self.client.location.cities(
            filter_params=CityListFilter(
                country_codes=country_code,
                city=city,
                postal_code=postal_code or None,
                size=1,
            )  # pyright: ignore
        )

        if not cities:
            raise ValidationError(
                _(
                    "City with name %(city)s and country %(code)s not found",
                    {"city": city, "code": country_code},
                )
            ) from None
        return cities[0]

    def get_offices(self, params) -> list[OfficeResponse]:
        """Fetch CDEK pickup offices matching the given filters.

        Args:
            params: Filter values accepted by :class:`OfficeFilter`.

        Returns:
            list[OfficeResponse]: Matching office records from CDEK.
        """
        return self.client.office._get_offices(
            OfficeFilter.model_validate(params)  # pyright: ignore
        )

    def get_shipping_partner_tariff_code(self, partner) -> int:
        """Return the CDEK tariff code configured on the shipping partner.

        Args:
            partner: ``res.partner`` shipping address record.

        Returns:
            int: CDEK tariff code.

        Raises:
            ValidationError: If the tariff is missing or incompatible with the carrier.
        """
        tariff = partner.cdek_tariff_mode_id
        if not tariff:
            raise ValidationError(
                _("Tariff is not set for partner %s", partner.display_name)
            ) from None
        if tariff.delivery_from != self.carrier.cdek_default_delivery_type:
            raise ValidationError(
                _(
                    "Invalid tariff for partner %(partner)s\n"
                    "Default delivery type: %(delivery_type)s\n"
                    "Tariff delivery from: %(delivery_from)s",
                    {
                        "partner": partner.display_name,
                        "delivery_type": self.carrier.cdek_default_delivery_type,
                        "delivery_from": tariff.delivery_from,
                    },
                )
            ) from None
        return tariff.code

    def calculate(
        self, shipping_partner, sender, currency, packages, services
    ) -> TariffResponse | None:
        """Calculate delivery price via the CDEK tariff API.

        Args:
            shipping_partner: ``res.partner`` recipient address record.
            sender: ``res.partner`` sender address record.
            currency: ``res.currency`` record used for the calculation.
            packages: ``DeliveryPackage`` objects to ship.
            services: ``sale.order.cdek.service`` recordset of add-on services.

        Returns:
            TariffResponse | None: CDEK tariff calculation result.
        """
        return self.client.tariff.calc(
            TariffCodeRequest.model_validate(
                {
                    "type": self.carrier.cdek_type or 1,
                    "tariff_code": self.get_shipping_partner_tariff_code(
                        shipping_partner
                    ),
                    "currency": self.client.currency.get(currency.name),
                    "from_location": self._get_location(sender),
                    "to_location": self._get_location(shipping_partner),
                    "services": self._get_calc_services(services),
                    "packages": self._set_order_packages(packages),
                }
            )
        )

    def _set_order_location(self, partner, office_func, door_func):
        """Apply sender or recipient location to a CDEK order request.

        Dispatches to ``office_func`` or ``door_func`` depending on the
        partner delivery type.

        Args:
            partner: ``res.partner`` record with CDEK delivery settings.
            office_func: Callable that sets a CDEK office code on the order.
            door_func: Callable that sets a door-delivery location on the order.
        """
        if partner.cdek_delivery_type in ("office", "postbox"):
            office_func(partner.cdek_office_code)
        elif partner.cdek_delivery_type == "door":
            location = OrderLocation(**self._get_location(partner))  # type: ignore
            if partner.zip:
                location.postal_code = partner.zip
            door_func(location)

    def _set_order_items(self, package, package_obj) -> None:
        """Add commodity lines from a delivery package to a CDEK package.

        Args:
            package: ``DeliveryPackage`` with commodities to ship.
            package_obj: Mutable CDEK :class:`Package` being built.
        """
        for commodity in package.commodities:
            package_obj.add_item(
                name=commodity.product_id.display_name,
                ware_key=str(commodity.product_id.id),
                payment=Money(value=0.0, vat_sum=None, vat_rate=None),
                cost=round(commodity.monetary_value, 0),
                amount=commodity.qty,
                weight=self.carrier.convert_to_grams(
                    commodity.product_id.weight, self.weight_uom
                ),  # Convert kg to grams
            )

    def _create_order_packages(self, package) -> Package:
        """Build a CDEK package with dimensions, weight, and items.

        Args:
            package: ``DeliveryPackage`` to convert.

        Returns:
            Package: CDEK package ready to attach to an order request.
        """
        dimensions = package.dimension
        package_obj = Package.model_validate(
            dict(
                number=package.name,
                weight=self.carrier.convert_to_grams(
                    package.weight, self.weight_uom
                ),  # Convert kg to grams
                length=dimensions.get("length", self.carrier.default_length),
                width=dimensions.get("width", self.carrier.default_width),
                height=dimensions.get("height", self.carrier.default_height),
            )
        )
        self._set_order_items(package, package_obj)
        return package_obj

    def create_order(
        self,
        recipient,
        sender,
        seller=None,
        packages=None,
        services=None,
        order_number=None,
    ):
        """Create a shipping order in the CDEK API.

        Args:
            recipient: ``res.partner`` order recipient record.
            sender: ``res.partner`` sender record; required when ``order_type``
                is not ``"1"``.
            seller: Optional ``res.partner`` seller record.
            packages: ``DeliveryPackage`` objects included in the shipment.
            services: ``sale.order.cdek.service`` recordset of add-on services.
            order_number: Optional human-readable order reference.

        Returns:
            dict: Raw response from the CDEK order API.

        Raises:
            UserError: If order creation fails.
            ValidationError: If required order data is missing.
        """
        packages = packages or []
        services = services or []
        try:
            if not sender and self.order_type != "1":
                raise ValidationError(
                    _(
                        "Sender is required for order type %s",
                        _(ORDER_TYPE[self.order_type]),
                    )
                )
            order = OrderRequest(  # pyright: ignore
                number=order_number,
                type=self.order_type,
                tariff_code=recipient.cdek_tariff_mode_id.code,
                print=self.print_type,
                sender=Contact(  # pyright: ignore
                    name=sender.name
                ).add_phone(sender.get_cdek_phone())
                if sender
                else None,
                seller=Seller(  # pyright: ignore
                    name=seller.name,
                    phone=seller.phone,
                )
                if seller
                else None,
                recipient=Contact(  # pyright: ignore
                    name=recipient.name,
                ).add_phone(recipient.get_cdek_phone()),
                services=self._get_order_services(services),
            )
            self._set_order_location(
                partner=sender,
                office_func=order.set_shipment_point,
                door_func=order.set_from_location,
            )
            self._set_order_location(
                partner=recipient,
                office_func=order.set_delivery_point,
                door_func=order.set_to_location,
            )
            for package in packages:
                order.add_package(self._create_order_packages(package))
            return self.client.order.create(order)
        except Exception as e:
            raise UserError(_("Error creating order: %s", e)) from e

    def cancel_shipping(self, order_uuid) -> EntityResponse:
        """Cancel a CDEK order by UUID.

        Args:
            order_uuid: CDEK order UUID.

        Returns:
            EntityResponse: CDEK API response.

        Raises:
            UserError: If the cancellation request fails.
        """
        try:
            return self.client.order.refusal(order_uuid)
        except Exception as e:
            raise UserError(_("Error canceling order: %s", e)) from e

    def get_order_id(self, order_uuid) -> OrderEntityResponse:
        """Fetch a CDEK order by UUID.

        Args:
            order_uuid: CDEK order UUID.

        Returns:
            OrderEntityResponse: Order data returned by CDEK.

        Raises:
            UserError: If the request fails.
        """
        try:
            return self.client.order.get_by_uuid(order_uuid)
        except Exception as e:
            raise UserError(_("Error getting order id: %s", e)) from e

    def get_tariffs(self) -> list:
        """Fetch all available CDEK tariff codes.

        Returns:
            list: Tariff codes returned by the CDEK API.

        Raises:
            UserError: If the request fails.
        """
        try:
            result = self.client.tariff.all()
            return result.get_codes()
        except Exception as e:
            raise UserError(_("Error getting tariffs: %s", e)) from e

    def delete_order(self, uuid) -> EntityResponse:
        """Delete a CDEK order by UUID.

        Args:
            uuid: CDEK order UUID.

        Returns:
            EntityResponse: CDEK API response.

        Raises:
            UserError: If the deletion request fails.
        """
        try:
            return self.client.order.delete(uuid)
        except Exception as e:
            raise UserError(_("Error deleting order: %s", e)) from e

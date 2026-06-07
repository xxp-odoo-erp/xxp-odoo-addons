# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import time
from typing import Any

from odoo import _, api, fields, models, registry
from odoo.exceptions import UserError, ValidationError

from ..const import DELIVERY_TYPE_FROM
from ..tools.cdek_request import CdekRequest


class DeliveryCarrier(models.Model):
    """Extend ``delivery.carrier`` with CDEK shipping integration.

    Adds API credentials, tariff settings, rate calculation, shipment
    creation, tracking links, and tariff synchronization from the CDEK API.
    """

    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(
        selection_add=[("cdek", "CDEK")],
        ondelete={
            "cdek": lambda recs: recs.write(
                {"delivery_type": "fixed", "fixed_price": 0}
            )
        },
    )
    cdek_type = fields.Selection(
        [("1", "E-Commerce"), ("2", "Delivery")],
        default="1",
        help="Order type for CDEK delivery",
    )
    cdek_default_delivery_type = fields.Selection(
        DELIVERY_TYPE_FROM,
        string="Default Delivery Type",
        default="office",
        help="Default delivery type for CDEK delivery",
    )
    cdek_print_type = fields.Selection(
        [("WAYBILL", "Waybill"), ("BARCODE", "Barcode")],
        default="WAYBILL",
        help="Print type for CDEK delivery",
    )
    cdek_available_tariff_ids = fields.Many2many("cdek.tariff.mode")

    # Dimensions
    default_length = fields.Float(default=1)
    default_width = fields.Float(default=1)
    default_height = fields.Float(default=1)

    # API credentials
    cdek_client_id = fields.Char()
    cdek_client_secret = fields.Char()
    cdek_delivery_lead_time = fields.Integer(default=0)

    def _compute_can_generate_return(self):
        """Allow return label generation for CDEK carriers."""
        result = super()._compute_can_generate_return()
        for carrier in self.filtered(lambda c: c.delivery_type == "cdek"):
            carrier.can_generate_return = True
        return result

    def _compute_supports_shipping_insurance(self):
        """Mark CDEK carriers as supporting shipping insurance."""
        result = super()._compute_supports_shipping_insurance()
        for carrier in self:
            is_cdek_delivery_type = carrier.delivery_type == "cdek"
            if is_cdek_delivery_type:
                carrier.supports_shipping_insurance = is_cdek_delivery_type
        return result

    def _get_cdek_carriers_domain(self) -> list[tuple[str, str, Any]]:
        """Return a search domain that selects CDEK delivery carriers.

        Returns:
            list[tuple[str, str, Any]]: Domain filtering on ``delivery_type``.
        """
        return [("delivery_type", "=", "cdek")]

    def _cdek_request(self) -> CdekRequest:
        """Build a CDEK API client for the current carrier record.

        Raises:
            UserError: If the recordset is empty or contains no CDEK carrier.

        Returns:
            CdekRequest: Configured client bound to this carrier.
        """
        if not self:
            raise UserError(_("CDEK delivery carrier is not specified"))
        cdek_carriers = self.filtered_domain(self._get_cdek_carriers_domain())
        if not cdek_carriers:
            raise UserError(_("CDEK delivery not found"))
        cdek_carriers.ensure_one()
        return CdekRequest(cdek_carriers)

    def convert_to_grams(self, measure, weight_uom):
        """Convert a weight measure to grams for the CDEK API.

        Args:
            measure: Weight value in ``weight_uom``.
            weight_uom: ``uom.uom`` record of the source weight unit.

        Returns:
            float: Weight expressed in grams.
        """
        uom_grams = self.env.ref("uom.product_uom_gram")
        return weight_uom._compute_quantity(
            qty=measure,
            to_unit=uom_grams,
            round=False,
        )

    def _rate_params(
        self,
        success=False,
        price=0.0,
        services=None,
        error_message=None,
        warning_message=None,
    ):
        """Build the dict returned by Odoo ``rate_shipment`` hooks.

        Args:
            success: Whether the rate request succeeded.
            price: Quoted delivery price.
            services: Optional extra service pricing data.
            error_message: Error text shown when ``success`` is ``False``.
            warning_message: Non-blocking warning text for the user.

        Returns:
            dict: Keys ``success``, ``price``, ``error_message``,
            ``warning_message``, and optionally ``services``.
        """
        result = {
            "success": success,
            "price": price,
            "error_message": error_message,
            "warning_message": warning_message,
        }
        if services:
            result["services"] = services
        return result

    def cdek_rate_shipment(self, order):
        """Quote CDEK delivery price for a sales order.

        Validates packages against the partner tariff and calls the CDEK
        tariff API. Updates line totals on ``sale.order.cdek.service`` when
        the API returns service prices.

        Args:
            order: ``sale.order`` to rate.

        Returns:
            dict: Result from ``_rate_params`` (success, price, errors).
        """
        cdek = self._cdek_request()
        if not order.partner_shipping_id:
            return self._rate_params(error_message=_("Delivery address not specified!"))
        try:
            packages = self._get_packages_from_order(order, order.cdek_package_type_id)
            partner_shipping = order.partner_shipping_id or order.partner_id
            if not partner_shipping.cdek_tariff_mode_id:
                return self._rate_params(
                    error_message=_(
                        "CDEK: Tariff is not set for partner %s",
                        partner_shipping.display_name,
                    )
                )
            partner_shipping.cdek_tariff_mode_id._check_package_tariff(packages)
            services_object = {
                service.product_id.cdek_reference: service
                for service in order.cdek_service_ids
            }
            response = cdek.calculate(
                partner_shipping,
                sender=order.warehouse_id.partner_id,
                currency=order.pricelist_id.currency_id,
                packages=packages,
                services=order.cdek_service_ids,
            )
            if response:
                for service in response.services or []:
                    if service.code in services_object:
                        services_object[service.code].total_price = service.total_sum
                return self._rate_params(
                    success=True,
                    price=response.total_sum,
                )
        except Exception as e:
            return self._rate_params(error_message=str(e))

        return self._rate_params(error_message=_("Unknown error"))

    def _create_error_message(self, requests_):
        """Concatenate error messages from CDEK API request objects.

        Args:
            requests_: Iterable of CDEK payloads exposing an ``errors`` list.

        Returns:
            str | bool: Joined messages, or ``False`` when there are no errors.
        """
        errors_list = []
        for req in requests_:
            for error in req.errors or []:
                errors_list.append(error.message)
        if errors_list:
            return "\n".join(errors_list)
        return False

    def _get_cdek_order_status(self, cdek, order_uuid, counter=0):
        """Poll CDEK until an order leaves the ``ACCEPTED`` processing state.

        Waits between requests and retries while CDEK still processes the order.

        Args:
            cdek: ``CdekRequest`` client used to fetch the order.
            order_uuid: CDEK order UUID.
            counter: Retry counter for long-running ``ACCEPTED`` status.

        Returns:
            tuple: ``(entity, error_message, is_long_operation)`` where
            ``entity`` is the CDEK order entity on success.
        """
        time.sleep(5)
        try:
            response = cdek.get_order_id(order_uuid)
        except Exception as e:
            return "", str(e), False
        status = response.entity.statuses[0].code
        if status == "INVALID":
            error_messages = self._create_error_message(response.requests)
            return "", error_messages, False
        elif status == "ACCEPTED":
            if counter >= 10:
                return "", _("Long operation please try again later!"), True
            return self._get_cdek_order_status(cdek, order_uuid, counter + 1)
        return response.entity, "", False

    def cdek_send_shipping(self, pickings):
        """Create CDEK orders for pickings and return tracking data.

        Hook invoked by the delivery module when validating shipments.

        Args:
            pickings: ``stock.picking`` recordset to ship via CDEK.

        Returns:
            list[dict]: Per-picking dicts with ``tracking_number`` and
            ``exact_price``.

        Raises:
            ValidationError: If the partner tariff is missing or packages are invalid.
            UserError: If order creation or status polling fails.
        """
        res = []
        cdek = self._cdek_request()
        for picking in pickings:
            packages = self._get_packages_from_picking(
                picking, picking.sale_id.cdek_package_type_id
            )
            partner_shipping = picking.partner_id
            if not partner_shipping.cdek_tariff_mode_id:
                raise ValidationError(
                    _(
                        "CDEK: Tariff is not set for partner %s",
                        partner_shipping.display_name,
                    )
                )
            partner_shipping.cdek_tariff_mode_id._check_package_tariff(packages)
            picking_id = picking.id
            if not picking.cdek_order_uuid:
                try:
                    result = cdek.create_order(
                        recipient=picking.partner_id,
                        sender=picking.picking_type_id.warehouse_id.partner_id,
                        seller=picking.company_id.partner_id,
                        packages=packages,
                        services=picking.sale_id.cdek_service_ids,
                        order_number=picking.name,
                    )
                    if (
                        result
                        and hasattr(result, "entity")
                        and result.entity
                        and hasattr(result.entity, "uuid")
                        and result.entity.uuid
                    ):
                        with registry(self._cr.dbname).cursor() as cr:
                            env = api.Environment(
                                cr, self.env.uid, dict(self.env.context)
                            )
                            env["stock.picking"].browse(picking_id).write(
                                {
                                    "cdek_order_uuid": result.entity.uuid,
                                }
                            )
                except ValidationError as e:
                    raise ValidationError(e.args[0]) from e
            entity, error_message, is_long_operation = self._get_cdek_order_status(
                cdek, picking.cdek_order_uuid
            )
            if error_message:
                if not is_long_operation:
                    with registry(self._cr.dbname).cursor() as cr:
                        env = api.Environment(cr, self.env.uid, dict(self.env.context))
                        env["stock.picking"].browse(picking_id).write(
                            {"cdek_order_uuid": False}
                        )
                raise UserError(_("CDEK Error: \n%s", error_message))
            res.append(
                {
                    "tracking_number": entity.cdek_number,
                    "exact_price": entity.delivery_detail
                    and entity.delivery_detail.total_sum
                    or 0,
                }
            )
        return res

    def cdek_get_tracking_link(self, picking):
        """Return the public CDEK tracking URL for a picking.

        Args:
            picking: ``stock.picking`` with ``carrier_tracking_ref`` set.

        Returns:
            str: Tracking URL, or an empty string when no tracking number exists.
        """
        if not picking.carrier_tracking_ref:
            return ""
        return (
            f"https://www.cdek.ru/ru/tracking/?order_id={picking.carrier_tracking_ref}"
        )

    def cdek_cancel_shipment(self, pickings):
        """Cancel CDEK shipments and clear tracking data on pickings.

        Args:
            pickings: ``stock.picking`` recordset with CDEK orders to cancel.
        """
        cdek = self._cdek_request()
        for picking in pickings:
            cdek.cancel_shipping(picking.cdek_order_uuid)
            picking.message_post(
                body=_("Shipment #%s was canceled", picking.carrier_tracking_ref)
            )
            picking.update(
                {
                    "carrier_tracking_ref": "",
                    "carrier_price": 0.0,
                    "cdek_order_uuid": False,
                }
            )
        return

    def _cdek_get_default_custom_package_code(self):
        """Return the default package type code used for CDEK pickings."""
        return "CDEK"

    def action_upload_cdek_tariffs(self):
        """Synchronize tariffs and modes from the CDEK API.

        Returns:
            dict: ``ir.actions.client`` notification action parameters.
        """
        cdek = self._cdek_request()
        tariffs_result = cdek.get_tariffs()
        self.env["cdek.tariff"].get_or_create(tariffs_result)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Tariffs loaded!"),
                "message": _("CDEK tariffs have been synchronized!"),
                "sticky": False,
            },
        }

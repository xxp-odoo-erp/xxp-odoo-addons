# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


class ChooseDeliveryCarrier(models.TransientModel):
    """Extend the delivery carrier wizard for CDEK quoting.

    Exposes CDEK services, package type, tariff mode, and dimension hints on
    the standard ``choose.delivery.carrier`` form used to rate sales orders.
    """

    _inherit = "choose.delivery.carrier"

    display_price = fields.Float(readonly=False)
    order_cdek_service_ids = fields.One2many(
        related="order_id.cdek_service_ids", readonly=False, string="Services"
    )
    order_package_type_id = fields.Many2one(
        related="order_id.cdek_package_type_id",
        string="Package Type",
        readonly=False,
    )
    cdek_delivery_type = fields.Selection(
        related="order_id.partner_shipping_id.cdek_delivery_type",
    )
    order_partner_tariff_id = fields.Many2one(
        related="order_id.cdek_tariff_mode_id",
        string="Partner Tariff",
    )
    order_package_dimensions = fields.Char(
        related="order_package_type_id.dimensions",
        string="Package Dimensions",
    )
    partner_tariff_dimensions = fields.Char(
        related="order_partner_tariff_id.dimensions",
        string="Tariff Dimensions",
    )
    carrier_delivery_type = fields.Selection(
        related="carrier_id.delivery_type", string="Carrier Delivery Type"
    )

    def update_price(self):
        """Require a package type before rating a CDEK delivery.

        Raises:
            UserError: If the carrier is CDEK and no package type is selected.

        Returns:
            dict: Action returned by the parent ``update_price`` implementation.
        """
        if self.carrier_delivery_type == "cdek" and not self.order_package_type_id:
            raise UserError(_("Please select a package type."))
        return super().update_price()

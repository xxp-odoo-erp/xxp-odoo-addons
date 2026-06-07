# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class SaleOrder(models.Model):
    """Extend sales orders with CDEK delivery data.

    Adds additional service lines, package type, and a stored copy of the
    shipping partner's CDEK tariff mode for rate calculation and shipping.
    """

    _inherit = "sale.order"

    carrier_type = fields.Selection(related="carrier_id.delivery_type", store=True)
    cdek_service_ids = fields.One2many(
        "sale.order.cdek.service", "order_id", domain="[('product_id', '!=', False)]"
    )
    cdek_package_type_id = fields.Many2one("stock.package.type")
    cdek_tariff_mode_id = fields.Many2one(
        "cdek.tariff.mode",
        compute="_compute_cdek_tariff_mode_id",
        store=True,
    )

    @api.depends(
        "partner_id",
        "partner_id.cdek_delivery_type",
        "partner_id.cdek_tariff_mode_id",
        "partner_shipping_id",
        "partner_shipping_id.cdek_delivery_type",
        "partner_shipping_id.cdek_tariff_mode_id",
    )
    def _compute_cdek_tariff_mode_id(self):
        """Mirror the CDEK tariff mode from the shipping or main partner."""
        for record in self:
            partner = record.partner_shipping_id or record.partner_id
            record.cdek_tariff_mode_id = partner.cdek_tariff_mode_id

# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class StockPicking(models.Model):
    """Extend pickings with the CDEK order UUID.

    Stores the UUID returned when a shipment is registered in CDEK and is
    used to poll order status, fetch tracking numbers, and cancel shipments.
    """

    _inherit = "stock.picking"

    cdek_order_uuid = fields.Char()

# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class StockPackageLevel(models.Model):
    """Extend package types with CDEK carrier support.

    Adds the CDEK ``package_carrier_type`` option and a computed dimensions
    summary used on sales orders and delivery wizards.
    """

    _inherit = "stock.package.type"

    package_carrier_type = fields.Selection(
        selection_add=[("cdek", "CDEK")],
        ondelete={"cdek": lambda recs: recs.write({"package_carrier_type": "none"})},
    )

    dimensions = fields.Char(compute="_compute_dimensions")

    def _compute_dimensions(self):
        """Build a human-readable length × width × height and max weight string."""
        for record in self:
            record.dimensions = (
                f"{record.packaging_length}x{record.width}x{record.height} cm"
                f" {record.max_weight} {record.weight_uom_name}"
            )

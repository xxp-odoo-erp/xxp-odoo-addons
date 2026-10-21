# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    barcode_shortcut = fields.Boolean(
        string="Barcode App Shortcut",
        help="Show a shortcut button for this operation type "
        "on the Barcode app main screen.",
    )
    barcode_shortcut_sequence = fields.Integer(
        string="Barcode App Shortcut Sequence",
        default=10,
        help="Order of the shortcut button on the Barcode app main screen. "
        "Lower values are shown first.",
    )

    @api.model
    def get_barcode_shortcuts(self):
        """Return the operation types shown as shortcuts on the Barcode main screen.

        Multi-company record rules are applied by the regular ORM search, so
        the current user only gets the operation types of the companies
        available to him.

        Returns:
            list[dict]: ``{"id", "name"}`` per enabled operation type, ordered
            by ``barcode_shortcut_sequence``. ``name`` is the shortcut label,
            see :meth:`_get_barcode_shortcut_name`.
        """
        picking_types = self.search(
            [("barcode_shortcut", "=", True)],
            order="barcode_shortcut_sequence, sequence, id",
        )
        with_prefix = self.env["stock.warehouse"].search_count([]) > 1
        return [
            {
                "id": picking_type.id,
                "name": picking_type._get_barcode_shortcut_name(with_prefix),
            }
            for picking_type in picking_types
        ]

    def _get_barcode_shortcut_name(self, with_prefix):
        """Return the label of the shortcut button.

        The warehouse code is used instead of the warehouse name: the name is
        often long (company name) and does not fit on the button.

        Args:
            with_prefix (bool): Prepend the warehouse code when the operation
                type belongs to a warehouse.

        Returns:
            str: ``"<warehouse code>: <name>"`` or the plain operation type name.
        """
        self.ensure_one()
        if with_prefix and self.warehouse_id.code:
            return f"{self.warehouse_id.code}: {self.name}"
        return self.name

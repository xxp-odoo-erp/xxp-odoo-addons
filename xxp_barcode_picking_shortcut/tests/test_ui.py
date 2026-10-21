# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestBarcodePickingShortcutUI(HttpCase):
    """Barcode app main screen: tooltip helper and shortcut buttons."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.picking_type = cls.env["stock.picking.type"].create(
            {
                "name": "Shortcut Tour",
                "code": "internal",
                "sequence_code": "SHT",
                "warehouse_id": warehouse.id,
                "barcode_shortcut": True,
                "barcode_shortcut_sequence": 1,
            }
        )

    def test_main_menu_shortcut_tour(self):
        """Shortcut button is shown on the main screen and opens the operations."""
        action = self.env.ref("stock_barcode.stock_barcode_action_main_menu")
        self.start_tour(
            "/web#action=%s" % action.id,
            "xxp_barcode_picking_shortcut_main_menu",
            login="admin",
        )

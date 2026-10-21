# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo.tests.common import TransactionCase, tagged


# post_install: the multi-company test creates a company, which needs the full
# registry (NOT NULL columns of modules that are not dependencies of this one).
@tagged("post_install", "-at_install")
class TestStockPickingTypeBarcodeShortcut(TransactionCase):
    """Selection and ordering of the Barcode app shortcut operation types."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.picking_type_obj = cls.env["stock.picking.type"]
        # Make sure no pre-existing operation type pollutes the shortcut list.
        cls.picking_type_obj.search([("barcode_shortcut", "=", True)]).write(
            {"barcode_shortcut": False}
        )
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        # Company 2 is isolated: it gets exactly one warehouse on creation, so
        # the warehouse prefix cases can be tested without touching company 1.
        cls.company_2 = cls.env["res.company"].create({"name": "Shortcut Company 2"})
        cls.warehouse_company_2 = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company_2.id)]
        )
        cls.user_company_2 = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "Shortcut User Company 2",
                    "login": "shortcut_user_company_2",
                    "company_id": cls.company_2.id,
                    "company_ids": [(6, 0, [cls.company_2.id])],
                    "groups_id": [(6, 0, [cls.env.ref("stock.group_stock_user").id])],
                }
            )
        )

    def _create_picking_type(self, name, shortcut_sequence, **extra_vals):
        """Create an internal operation type enabled as a Barcode app shortcut.

        Args:
            name (str): Operation type name.
            shortcut_sequence (int): Value of ``barcode_shortcut_sequence``.
            **extra_vals: Extra values merged into the create dict.

        Returns:
            recordset: The created ``stock.picking.type`` record.
        """
        vals = {
            "name": name,
            "code": "internal",
            "sequence_code": name[:3].upper(),
            "warehouse_id": self.warehouse.id,
            "barcode_shortcut": True,
            "barcode_shortcut_sequence": shortcut_sequence,
        }
        vals.update(extra_vals)
        return self.picking_type_obj.create(vals)

    def test_no_shortcuts(self):
        """No shortcut is returned when no operation type is enabled."""
        self.assertEqual(
            self.picking_type_obj.get_barcode_shortcuts(),
            [],
            "Shortcut list must be empty when no operation type is enabled",
        )

    def test_shortcuts_ordered_by_shortcut_sequence(self):
        """Shortcuts follow the Barcode App Shortcut Sequence, not creation order."""
        third = self._create_picking_type("Third", 30)
        first = self._create_picking_type("First", 10)
        second = self._create_picking_type("Second", 20)

        shortcuts = self.picking_type_obj.get_barcode_shortcuts()
        self.assertEqual(
            [shortcut["id"] for shortcut in shortcuts],
            [first.id, second.id, third.id],
            "Shortcuts must be ordered by barcode_shortcut_sequence",
        )

    def test_shortcuts_same_shortcut_sequence_fallback(self):
        """Equal shortcut sequences fall back to the operation type sequence."""
        later = self._create_picking_type("Later", 10, sequence=50)
        sooner = self._create_picking_type("Sooner", 10, sequence=5)

        shortcuts = self.picking_type_obj.get_barcode_shortcuts()
        self.assertEqual(
            [shortcut["id"] for shortcut in shortcuts],
            [sooner.id, later.id],
            "Equal shortcut sequences must be ordered by the standard sequence",
        )

    def test_disabled_shortcut_not_returned(self):
        """Operation types without the checkbox are not shown as shortcuts."""
        enabled = self._create_picking_type("Enabled", 10)
        disabled = self._create_picking_type("Disabled", 5, barcode_shortcut=False)

        shortcut_ids = [
            shortcut["id"] for shortcut in self.picking_type_obj.get_barcode_shortcuts()
        ]
        self.assertIn(enabled.id, shortcut_ids, "Enabled type must be a shortcut")
        self.assertNotIn(
            disabled.id, shortcut_ids, "Disabled type must not be a shortcut"
        )

    def _get_company_2_shortcuts(self):
        """Return the shortcuts as seen by the company 2 user.

        Returns:
            list[dict]: Result of ``get_barcode_shortcuts`` for company 2.
        """
        return self.picking_type_obj.with_user(
            self.user_company_2
        ).get_barcode_shortcuts()

    def test_shortcut_name_single_warehouse(self):
        """With a single warehouse the label is the plain operation type name."""
        self.assertEqual(
            len(self.warehouse_company_2), 1, "Company 2 must have one warehouse"
        )
        self._create_picking_type(
            "Internal Transfer",
            10,
            warehouse_id=self.warehouse_company_2.id,
            company_id=self.company_2.id,
        )

        shortcuts = self._get_company_2_shortcuts()
        self.assertEqual(
            [shortcut["name"] for shortcut in shortcuts],
            ["Internal Transfer"],
            "Single warehouse must not add a prefix to the shortcut name",
        )

    def test_shortcut_name_multi_warehouse_code_prefix(self):
        """With several warehouses the label is prefixed by the warehouse code."""
        self.env["stock.warehouse"].create(
            {"name": "Second Warehouse", "code": "WH2", "company_id": self.company_2.id}
        )
        self._create_picking_type(
            "Internal Transfer",
            10,
            warehouse_id=self.warehouse_company_2.id,
            company_id=self.company_2.id,
        )

        shortcuts = self._get_company_2_shortcuts()
        self.assertEqual(
            [shortcut["name"] for shortcut in shortcuts],
            ["%s: Internal Transfer" % self.warehouse_company_2.code],
            "Shortcut name must be prefixed by the warehouse code",
        )
        self.assertNotIn(
            self.warehouse_company_2.name,
            shortcuts[0]["name"],
            "Shortcut name must not contain the warehouse name",
        )

    def test_shortcut_name_without_warehouse(self):
        """An operation type without warehouse never gets a prefix."""
        self.env["stock.warehouse"].create(
            {"name": "Second Warehouse", "code": "WH2", "company_id": self.company_2.id}
        )
        self._create_picking_type(
            "No Warehouse", 10, warehouse_id=False, company_id=self.company_2.id
        )

        shortcuts = self._get_company_2_shortcuts()
        self.assertEqual(
            [shortcut["name"] for shortcut in shortcuts],
            ["No Warehouse"],
            "Operation type without warehouse must keep its plain name",
        )

    def test_shortcuts_respect_multi_company(self):
        """A user of another company does not see the shortcuts of this company."""
        self._create_picking_type("Company 1 Shortcut", 10)

        shortcuts = self.picking_type_obj.with_user(
            self.user_company_2
        ).get_barcode_shortcuts()
        self.assertEqual(
            shortcuts,
            [],
            "Operation types of another company must not be returned",
        )

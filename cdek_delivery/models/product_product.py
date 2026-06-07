# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..const import CDEK_REFERENCE_SELECTION, CDEK_SERVICE_TYPE


class ProductProduct(models.Model):
    """Extend products with CDEK additional service configuration.

    Links a product variant to a CDEK service code and derives the value
    type (counter, price, length, phone) used on sale order service lines.
    """

    _inherit = "product.product"

    _sql_constraints = [
        (
            "cdek_reference_uniq",
            "unique(cdek_reference)",
            "CDEK reference must be unique",
        )
    ]

    def _get_cdek_reference_selection(self):
        """Return CDEK service codes as a translatable selection list."""
        return [(k, _(v)) for k, v in CDEK_REFERENCE_SELECTION.items()]

    cdek_reference = fields.Selection(selection=_get_cdek_reference_selection)
    cdek_reference_type = fields.Selection(
        selection=[
            ("counter", "Counter"),
            ("price", "Price"),
            ("length", "Length"),
            ("phone", "Phone"),
        ],
        compute="_compute_cdek_reference_type",
        string="CDEK Reference Type",
    )

    def _compute_cdek_reference_type(self):
        """Derive the CDEK value type from the selected service code."""
        for record in self:
            reference_type = None
            for service_type, services in CDEK_SERVICE_TYPE.items():
                if record.cdek_reference in services:
                    reference_type = service_type
                    break
            record.cdek_reference_type = reference_type

    @api.constrains("cdek_reference", "detailed_type", "sale_ok", "purchase_ok")
    def _check_cdek_reference(self):
        """Ensure CDEK references are used only on internal service products.

        CDEK additional services must not be sold or purchased as regular
        catalog items.

        Raises:
            ValidationError: If ``cdek_reference`` is set on a non-service
                product or on a saleable/purchasable product.
        """
        for record in self:
            if record.cdek_reference and record.detailed_type != "service":
                raise ValidationError(
                    _("CDEK service can only be used for service products")
                )
            if record.cdek_reference and (record.sale_ok or record.purchase_ok):
                raise ValidationError(
                    _("CDEK service cannot be used for saleable products")
                )

    @api.onchange("cdek_reference")
    def _onchange_cdek_reference(self):
        """Clear sale and purchase flags when a CDEK service is selected."""
        if self.cdek_reference:
            self.update({"sale_ok": False, "purchase_ok": False})

# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import _, api, fields, models

from ..const import CDEK_REFERENCE_SELECTION


class ProductTemplate(models.Model):
    """Expose CDEK service code on product templates.

    Mirrors ``cdek_reference`` from the first variant and propagates template
    changes back to all variants for single- and multi-variant products.
    """

    _inherit = "product.template"

    cdek_reference = fields.Selection(
        selection=list(CDEK_REFERENCE_SELECTION.items()),
        compute="_compute_cdek_reference",
        inverse="_inverse_cdek_reference",
        store=True,
        readonly=False,
    )

    @api.depends("product_variant_ids", "product_variant_ids.cdek_reference")
    def _compute_cdek_reference(self):
        """Set template CDEK code from the first variant's ``cdek_reference``."""
        for template in self:
            variant = template.product_variant_ids[:1]
            template.cdek_reference = variant.cdek_reference if variant else False

    def _inverse_cdek_reference(self):
        """Write the template CDEK code to every product variant."""
        for template in self:
            if not template.product_variant_ids:
                continue
            for variant in template.product_variant_ids:
                variant.cdek_reference = template.cdek_reference

    @api.onchange("cdek_reference")
    def _onchange_cdek_reference(self):
        """Prefill template fields when a CDEK service code is selected.

        Sets a default name, clears sale/purchase flags, zeroes list price, and
        stores the API code in ``default_code``.
        """
        if self.cdek_reference:
            reference_name = _(CDEK_REFERENCE_SELECTION[self.cdek_reference])
            self.update(
                {
                    "name": _("CDEK - %s", reference_name),
                    "sale_ok": False,
                    "purchase_ok": False,
                    "list_price": 0,
                    "default_code": self.cdek_reference,
                }
            )

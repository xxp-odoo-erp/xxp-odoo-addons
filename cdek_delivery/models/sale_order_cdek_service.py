# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..const import SERVICE_VALUE_ERRORS, SERVICE_VALUE_FIELDS


class SaleOrderCdekService(models.Model):
    """CDEK additional service line on a sales order.

    Stores the service product and typed parameter (quantity, price, length,
    or phone) sent to the CDEK API during rate calculation and shipping.
    """

    _name = "sale.order.cdek.service"
    _description = "Sale Order CDEK Service"

    order_id = fields.Many2one("sale.order", required=True)
    company_id = fields.Many2one(
        related="order_id.company_id",
        store=True,
        readonly=True,
        precompute=True,
        index=True,
    )
    company_currency_id = fields.Many2one(related="company_id.currency_id")
    product_id = fields.Many2one(
        "product.product",
        domain="[('cdek_reference', '!=', False)]",
        string="Service",
        required=True,
    )
    product_cdek_reference_type = fields.Selection(
        related="product_id.cdek_reference_type"
    )

    counter_value = fields.Integer()
    price_value = fields.Float()
    length_value = fields.Float()
    phone_value = fields.Char()
    value = fields.Char(compute="_compute_value")
    total_price = fields.Monetary(currency_field="company_currency_id")

    @api.constrains(
        "product_id", "counter_value", "price_value", "length_value", "phone_value"
    )
    def _check_value(self):
        """Validate the service parameter matching the product's CDEK type.

        Uses ``SERVICE_VALUE_FIELDS`` to pick the active field and validator
        (counter, price, length, or phone).

        Raises:
            ValidationError: If the typed value fails validation for the service.
        """
        for record in self:
            reference_type = record.product_cdek_reference_type
            field_name, validator = SERVICE_VALUE_FIELDS.get(
                reference_type, (None, None)
            )
            if field_name and validator and not validator(record[field_name]):
                error_message = _(
                    "%(product)s: %(error)s",
                    product=record.product_id.display_name,
                    error=SERVICE_VALUE_ERRORS[reference_type],
                )
                raise ValidationError(error_message)

    def _compute_value(self):
        """Expose the active typed field as a single character ``value``."""
        for record in self:
            field_name, _ = SERVICE_VALUE_FIELDS.get(
                record.product_cdek_reference_type, (None, None)
            )
            record.value = record[field_name] if field_name else ""

    def write(self, vals):
        """Delete the line when it is removed from the order's One2many field.

        Odoo writes ``order_id`` to ``False`` when the user deletes the line in
        the UI; unlink the record instead of leaving an orphan row.
        """
        if "order_id" in vals and vals.get("order_id") is False:
            self.unlink()
            return True
        return super().write(vals)

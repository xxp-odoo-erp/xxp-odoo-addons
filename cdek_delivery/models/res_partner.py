# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..const import DELIVERY_METHODS


class ResPartner(models.Model):
    """Extend partners with CDEK delivery settings.

    Stores city and office codes, delivery type, tariff mode, and helpers
    used when quoting and creating CDEK shipments.
    """

    _inherit = "res.partner"

    cdek_city_code = fields.Char(
        string="City Code", help="CDEK City Code from CDEK API"
    )
    cdek_office_code = fields.Char(
        string="Office", help="CDEK Office Code from CDEK API"
    )
    cdek_delivery_type = fields.Selection(
        DELIVERY_METHODS, string="Delivery Type", copy=False
    )

    cdek_tariff_mode_id = fields.Many2one(
        "cdek.tariff.mode",
    )
    cdek_tariff_mode_domain = fields.Binary(
        string="CDEK Tariff Mode Domain",
        compute="_compute_cdek_tariff_mode_domain",
    )
    delivery_carrier_type = fields.Selection(
        related="property_delivery_carrier_id.delivery_type"
    )
    cdek_contragent_type = fields.Selection(
        selection=[("LEGAL_ENTITY", "Legal Entity"), ("INDIVIDUAL", "Individual")],
        compute="_compute_cdek_contragent_type",
        readonly=False,
        store=True,
        help="Contragent type for CDEK delivery",
    )

    @api.constrains(
        "cdek_tariff_mode_id", "cdek_delivery_type", "property_delivery_carrier_id"
    )
    def _check_cdek_tariff_mode_id(self):
        """Validate tariff mode against carrier defaults and delivery type.

        Applies only when the partner's delivery carrier uses CDEK.

        Raises:
            ValidationError: If ``delivery_from`` or ``delivery_to`` on the
                selected mode does not match the carrier or partner settings.
        """
        for record in self:
            cdek_delivery = record.property_delivery_carrier_id
            if cdek_delivery.delivery_type != "cdek":
                continue
            cdek_default_from = cdek_delivery.cdek_default_delivery_type
            delivery_from = record.cdek_tariff_mode_id.delivery_from
            delivery_to = record.cdek_tariff_mode_id.delivery_to
            error_messages = []
            if delivery_from and cdek_default_from != delivery_from:
                delivery_method_label = dict(DELIVERY_METHODS).get(delivery_from)
                error_messages.append(
                    _(
                        "The tariff mode should be delivered from %s",
                        _(delivery_method_label) if delivery_method_label else "",
                    )
                )
            if record.cdek_delivery_type and record.cdek_delivery_type != delivery_to:
                to_label = dict(DELIVERY_METHODS).get(delivery_to, delivery_to)
                error_messages.append(
                    _("The tariff mode should be delivered to %s", _(to_label))
                )
            if error_messages:
                raise ValidationError("\n".join(error_messages)) from None

    @api.depends("cdek_delivery_type", "property_delivery_carrier_id")
    def _compute_cdek_tariff_mode_domain(self):
        """Build a domain that filters selectable CDEK tariff modes for the partner."""
        for record in self:
            cdek_delivery = record.property_delivery_carrier_id
            if cdek_delivery.delivery_type != "cdek":
                record.cdek_tariff_mode_domain = [("id", "=", False)]
                continue
            domain = []
            available_tariff_ids = cdek_delivery.cdek_available_tariff_ids
            if available_tariff_ids:
                domain.append(("id", "in", available_tariff_ids.ids))
            default_delivery_type = cdek_delivery.cdek_default_delivery_type
            if default_delivery_type:
                domain.append(("delivery_from", "=", default_delivery_type))
            delivery_type = record.cdek_delivery_type
            if delivery_type:
                domain.append(("delivery_to", "=", delivery_type))
            record.cdek_tariff_mode_domain = domain

    @api.depends("is_company")
    def _compute_cdek_contragent_type(self):
        """Map ``is_company`` to CDEK contragent type (legal entity or individual)."""
        for record in self:
            record.cdek_contragent_type = (
                record.is_company and "LEGAL_ENTITY" or "INDIVIDUAL"
            )

    @api.onchange("cdek_delivery_type")
    def _onchange_cdek_delivery_type(self):
        """Clear the tariff mode when the CDEK delivery type changes."""
        self.cdek_tariff_mode_id = False

    def open_cdek_point(self):
        """Open the CDEK office page for the partner's pickup point.

        Raises:
            UserError: If ``cdek_office_code`` is not set.

        Returns:
            dict: ``ir.actions.act_url`` action opening the office in a new tab.
        """
        self.ensure_one()
        if not self.cdek_office_code:
            raise UserError(_("Office code is not set"))
        return {
            "type": "ir.actions.act_url",
            "target": "new",
            "url": f"https://www.cdek.ru/ru/offices/view/{self.cdek_office_code}",
        }

    def get_cdek_phone(self):
        """Return the phone number sent to CDEK for this partner.

        Falls back to the parent company's phone when the contact has none.

        Returns:
            str: Phone number for CDEK order contacts.

        Raises:
            ValidationError: If neither the partner nor its parent has a phone.
        """
        if not self.phone and not self.parent_id.phone:
            raise ValidationError(
                _("CDEK phone is required for partner %s", self.display_name)
            )
        return self.phone or self.parent_id.phone

    def action_search_cdek_office(self):
        """Open the wizard to search and assign a CDEK pickup office.

        Returns:
            dict: ``ir.actions.act_window`` action for ``search.cdek.office``.
        """
        self.ensure_one()
        return {
            "name": _("Search CDEK Office"),
            "type": "ir.actions.act_window",
            "res_model": "search.cdek.office",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_partner_id": self.id,
                "default_city": self.city,
                "default_country_id": self.country_id.id,
                "default_zip": self.zip,
            },
        }

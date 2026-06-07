# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import logging

from cdek.apps.office import OfficeResponse
from cdek.exceptions import CdekException

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError

from ..const import OFFICE_TYPES

_logger = logging.getLogger(__name__)


class SearchCdekOffice(models.TransientModel):
    """Wizard to search CDEK pickup offices and assign one to a partner.

    Queries the CDEK API by city and office type, lists matching offices, and
    writes the selected office code and delivery type on ``res.partner``.
    """

    _name = "search.cdek.office"
    _description = "CDEK Search Office"

    def _default_country_id(self):
        """Return Russia as the default country for office search."""
        return self.env.ref("base.ru")

    def _selection_point_type(self):
        """Return translatable office type filters for the search form."""
        return [
            ("ALL", _("All Types")),
            ("PVZ", _("Office")),
            ("POSTAMAT", _("Postbox")),
        ]

    partner_id = fields.Many2one("res.partner", required=True, readonly=True)
    point_type = fields.Selection(
        selection=_selection_point_type,
        string="Type",
        default="ALL",
        help="By default All types",
    )
    city = fields.Char(required=True)
    country_id = fields.Many2one(
        "res.country", default=_default_country_id, required=True
    )
    zip = fields.Char()
    office_ids = fields.One2many("search.cdek.office.line", "search_id")

    def confirm(self, line):
        """Apply the selected office to the partner and close the wizard.

        Args:
            line: ``search.cdek.office.line`` record chosen by the user.

        Returns:
            dict: Client notification action confirming the selection.
        """
        self.ensure_one()
        code = line.code
        type_selection = dict(line._fields["type"]._description_selection(line.env))
        line_type = type_selection.get(line.type) or ""
        self.partner_id.write(
            {
                "cdek_office_code": code,
                "cdek_delivery_type": OFFICE_TYPES.get(line.type, None),
            }
        )
        self.office_ids.unlink()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Point selected"),
                "message": _(
                    "%(type)s %(code)s has been selected",
                    type=line_type,
                    code=code,
                ),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window_close",
                },
            },
        }

    def _prepare_query_office_params(self, **kwargs) -> dict:
        """Build filter parameters for the CDEK offices API request.

        Args:
            **kwargs: Extra filters (for example ``city_code``).

        Returns:
            dict: Params merged with the wizard ``point_type``.
        """
        return {"type": self.point_type, **kwargs}

    def _prepare_office_vals_list(self, offices: list[OfficeResponse]) -> list[dict]:
        """Map CDEK office responses to ``search.cdek.office.line`` create values.

        Args:
            offices: Offices returned by the CDEK API.

        Returns:
            list[dict]: Value dicts for One2many line creation.
        """
        return [
            {
                "code": office.code,
                "type": office.type,
                "address": office.location.address_full,
            }
            for office in offices
        ]

    def load(self):
        """Fetch CDEK offices for the current search criteria and refresh the form.

        Clears previous results, resolves the city code, queries offices, and
        populates ``office_ids``.

        Returns:
            dict: Window action reopening this wizard, or a client error
            notification when the API call fails.

        Raises:
            UserError: If no offices match the search parameters.
        """
        self.ensure_one()
        self.office_ids.unlink()
        cdek_request = self.env["delivery.carrier"]._cdek_request()
        try:
            city = cdek_request.get_city_code(
                city=self.city, country_code=self.country_id.code, postal_code=self.zip
            )
            params = self._prepare_query_office_params(city_code=city.code)
            offices = cdek_request.get_offices(params)
        except (CdekException, ValidationError, UserError) as e:
            _logger.error(e)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Error"),
                    "message": str(e),
                    "type": "error",
                    "sticky": True,
                    "next": {
                        "type": "ir.actions.act_window_close",
                    },
                },
            }
        if not offices:
            raise UserError(_("No offices found for current parameters"))
        vals_list = self._prepare_office_vals_list(offices)
        self.office_ids = [(0, 0, vals) for vals in vals_list]
        return {
            "name": _("Search CDEK Office"),
            "type": "ir.actions.act_window",
            "res_model": "search.cdek.office",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

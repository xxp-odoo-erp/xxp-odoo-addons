# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import _, fields, models


class SearchCdekOfficeLine(models.TransientModel):
    """Line in the CDEK office search wizard result list.

    Stores office code, type, and address until the user picks an office and
    confirms the selection on the parent ``search.cdek.office`` wizard.
    """

    _name = "search.cdek.office.line"
    _description = "Search CDEK Office Line"

    def _selection_type(self):
        """Return translatable labels for CDEK office types on the line."""
        return [
            ("PVZ", _("Office")),
            ("POSTAMAT", _("Postbox")),
        ]

    search_id = fields.Many2one("search.cdek.office", required=True, ondelete="cascade")
    code = fields.Char()
    type = fields.Selection(selection=_selection_type)
    address = fields.Char()

    def confirm(self):
        """Assign this office to the partner through the parent wizard.

        Returns:
            dict: Client notification action from ``search.cdek.office.confirm``.
        """
        self.ensure_one()
        return self.search_id.confirm(self)

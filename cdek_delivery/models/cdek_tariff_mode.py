# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from cdek.apps.tariff.responses import DeliveryMode
from cdek.constants import DELIVERY_METHODS as CDEK_DELIVERY_METHODS

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.delivery.models.delivery_request_objects import DeliveryPackage

from ..const import DELIVERY_METHODS


class CdekTariffMode(models.Model):
    """CDEK tariff delivery mode.

    Links a :model:`cdek.tariff` to a CDEK tariff code and stores the allowed
    delivery endpoints (from/to) for rate calculation and shipping.
    """

    _name = "cdek.tariff.mode"
    _description = "CDEK Tariff Mode"
    _rec_name = "display_name"

    display_name = fields.Char(compute="_compute_display_name")
    tariff_id = fields.Many2one("cdek.tariff", required=True)
    name = fields.Char(required=True, copy=False)
    mode = fields.Char(required=True, copy=False)
    code = fields.Integer(required=True, copy=False)
    delivery_from = fields.Selection(DELIVERY_METHODS, required=True, copy=False)
    delivery_to = fields.Selection(DELIVERY_METHODS, required=True, copy=False)
    dimensions = fields.Char(compute="_compute_dimensions")

    @api.depends(
        "tariff_id.length_max",
        "tariff_id.width_max",
        "tariff_id.height_max",
        "tariff_id.weight_max",
    )
    def _compute_dimensions(self) -> None:
        """Build a human-readable size and weight summary from the parent tariff."""
        for record in self:
            record.dimensions = (
                f"{record.tariff_id.length_max}x{record.tariff_id.width_max}x{record.tariff_id.height_max} cm"  # noqa: E501
                f" {record.tariff_id.weight_max} kg"
            )

    @api.depends("tariff_id.name", "name")
    def _compute_display_name(self) -> None:
        """Set display name to ``[code] tariff name - mode name``."""
        for record in self:
            record.display_name = (
                f"[{record.code}] {record.tariff_id.name} - {record.name}"
            )

    def _check_package_tariff(self, packages: list[DeliveryPackage]) -> None:
        """Validate delivery packages against this mode's tariff limits.

        Used before CDEK rate calculation and shipping to ensure dimensions
        and weight fit the selected tariff.

        Args:
            packages: ``DeliveryPackage`` objects to validate.

        Raises:
            ValidationError: If any package exceeds tariff size, weight, or
                volumetric weight limits.
        """
        self.ensure_one()
        for package in packages:
            if not self.tariff_id._check_size(**package.dimension):
                raise ValidationError(
                    _("Package size is not valid for tariff %s", self.display_name)
                ) from None
            if not self.tariff_id._check_weight(package.weight):
                raise ValidationError(
                    _("Package weight is not valid for tariff %s", self.display_name)
                ) from None
            if not self.tariff_id._check_weight_calc(package.weight):
                raise ValidationError(
                    _(
                        "Package weight calculation is not valid for tariff %s",
                        self.display_name,
                    )
                ) from None

    @api.model
    def get_or_create(self, tariff_id: int, delivery_modes: list[DeliveryMode]):
        """Create missing tariff modes from a CDEK API sync payload.

        Existing modes are matched by ``code`` and left unchanged.

        Args:
            tariff_id: Database ID of the parent ``cdek.tariff`` record.
            delivery_modes: Delivery modes returned by the CDEK tariffs API.

        Returns:
            recordset: Newly created ``cdek.tariff.mode`` records (empty if none).
        """
        modes = {
            mode.get("code"): mode.get("id") for mode in self.search_read([], ["code"])
        }
        vals_list = []
        for mode in delivery_modes:
            if modes.get(mode.tariff_code):
                continue
            delivery_from, delivery_to = CDEK_DELIVERY_METHODS.get(
                str(mode.delivery_mode), (None, None)
            )
            vals_list.append(
                {
                    "tariff_id": tariff_id,
                    "name": mode.delivery_mode_name,
                    "mode": mode.delivery_mode,
                    "code": mode.tariff_code,
                    "delivery_from": delivery_from,
                    "delivery_to": delivery_to,
                }
            )
        records = self.browse()
        if vals_list:
            records |= self.create(vals_list)
        return records

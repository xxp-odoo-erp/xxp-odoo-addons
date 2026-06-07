# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class CdekTariff(models.Model):
    """CDEK tariff with package dimension and weight limits.

    Stores min/max bounds synced from the CDEK API and groups related
    :model:`cdek.tariff.mode` records used for delivery rate calculation.
    """

    _name = "cdek.tariff"
    _description = "CDEK Tariff"

    name = fields.Char(required=True, copy=False)

    # Weight
    weight_min = fields.Float()
    weight_max = fields.Float()
    weight_calc_max = fields.Float()

    # Length
    length_min = fields.Integer()
    length_max = fields.Integer()

    # Width
    width_min = fields.Integer()
    width_max = fields.Integer()

    # Height
    height_min = fields.Integer()
    height_max = fields.Integer()

    mode_ids = fields.One2many("cdek.tariff.mode", "tariff_id")

    def _check_size(self, **kwargs) -> bool:
        """Return whether package dimensions fit this tariff's limits.

        Args:
            **kwargs: Expected keys ``length``, ``width``, and ``height`` (cm).

        Returns:
            bool: ``True`` when all dimensions are within min/max bounds.
        """
        self.ensure_one()
        length = kwargs.get("length", 0)
        width = kwargs.get("width", 0)
        height = kwargs.get("height", 0)
        if length < self.length_min or length > self.length_max:
            return False
        if width < self.width_min or width > self.width_max:
            return False
        if height < self.height_min or height > self.height_max:
            return False
        return True

    def _check_weight(self, weight: float) -> bool:
        """Return whether actual package weight fits this tariff's limits.

        Args:
            weight: Package weight in the carrier's weight UoM.

        Returns:
            bool: ``True`` when weight is between ``weight_min`` and ``weight_max``.
        """
        self.ensure_one()
        if weight < self.weight_min or weight > self.weight_max:
            return False
        return True

    def _check_weight_calc(self, weight: float) -> bool:
        """Return whether weight is within the tariff volumetric weight limit.

        Args:
            weight: Package weight used for volumetric checks.

        Returns:
            bool: ``True`` when weight does not exceed ``weight_calc_max``.
        """
        self.ensure_one()
        if weight > self.weight_calc_max:
            return False
        return True

    @api.model
    def _prepare_tariff_vals(self, tariff_obj) -> dict:
        """Map a CDEK API tariff payload to ``cdek.tariff`` create values.

        Args:
            tariff_obj: Tariff object returned by the CDEK tariffs API.

        Returns:
            dict: Values suitable for ``create()`` on this model.
        """
        return {
            "name": tariff_obj.tariff_name,
            "weight_min": tariff_obj.weight_min,
            "weight_max": tariff_obj.weight_max,
            "weight_calc_max": tariff_obj.weight_calc_max,
            "length_min": tariff_obj.length_min,
            "length_max": tariff_obj.length_max,
            "width_min": tariff_obj.width_min,
            "width_max": tariff_obj.width_max,
            "height_min": tariff_obj.height_min,
            "height_max": tariff_obj.height_max,
        }

    @api.model
    def get_or_create(self, tariffs_result: list):
        """Create missing tariffs from a CDEK API sync payload.

        Existing tariffs are matched by ``name`` and left unchanged. Delivery
        modes are always synchronized via ``cdek.tariff.mode.get_or_create``.

        Args:
            tariffs_result: Tariffs returned by the CDEK tariffs API.

        Returns:
            recordset: Newly created ``cdek.tariff`` records (empty if none).
        """
        tariffs = {
            mode.get("name"): mode.get("id") for mode in self.search_read([], ["name"])
        }
        new_records = self.browse()
        tariff_mode_obj = self.env["cdek.tariff.mode"]
        for tariff in tariffs_result:
            record = tariffs.get(tariff.tariff_name)
            if not record:
                record = self.create(self._prepare_tariff_vals(tariff))
                new_records |= record
            # Create modes
            tariff_mode_obj.get_or_create(record.id, tariff.delivery_modes or [])
        return new_records

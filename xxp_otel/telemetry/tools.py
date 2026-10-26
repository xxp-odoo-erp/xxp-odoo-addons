# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.models import origin_ids


def truncate(value: str, limit: int) -> str:
    """Truncate a string to a given length.

    Args:
        value: The string to truncate
        limit: The maximum length of the string

    Returns:
        A truncated string
    """
    return (
        value
        if len(value) <= limit
        else f"{value[:limit]}...<truncated:{len(value) - limit}>"
    )


def recordset_ids(records, limit):
    """Return at most ``limit`` ids of ``records`` without copying all of them.

    ``records.ids`` builds a list of every id, which is costly for the large
    recordsets that can reach an observed method.

    Args:
        records: The recordset to get the ids from
        limit: The maximum number of ids to return

    Returns:
        A list of ids
    """
    ids = getattr(records, "_ids", None)
    if isinstance(ids, tuple):
        return list(origin_ids(ids[:limit]))
    return list(records.ids)[:limit]

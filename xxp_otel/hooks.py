# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from .telemetry.runtime import runtime


def uninstall_hook(cr, registry):
    """Detach process-level logging integration on module uninstall.

    OpenTelemetry's global provider cannot be reset through the public API.
    Shutting down processors and removing our handler is therefore the safe
    process-local cleanup. A normal Odoo worker restart completes teardown.
    """
    runtime.shutdown()

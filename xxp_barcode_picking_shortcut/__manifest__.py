# Copyright (C) 2026 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

{
    "name": "Barcode Picking Shortcut",
    "summary": "Add picking operation shortcuts to the barcode App",
    "version": "16.0.1.0.0",
    "category": "Inventory/Inventory",
    "author": "XXP",
    "website": "https://xxp-odoo.com",
    "license": "LGPL-3",
    "application": False,
    "installable": True,
    "depends": ["stock_barcode"],
    "data": [
        "views/stock_picking_type_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "xxp_barcode_picking_shortcut/static/src/**/*",
        ],
        "web.assets_tests": [
            "xxp_barcode_picking_shortcut/static/tests/tours/**/*",
        ],
    },
}

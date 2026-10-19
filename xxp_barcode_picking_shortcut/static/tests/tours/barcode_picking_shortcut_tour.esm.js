/** @odoo-module **/
/* Copyright (C) 2026 XXP
 * License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl). */

import tour from "web_tour.tour";

tour.register("xxp_barcode_picking_shortcut_main_menu", {test: true}, [
    {
        // The helper text is gone from the screen: only the tooltip icon remains.
        trigger: ".o_stock_barcode_main_menu h1 .o_barcode_help_tooltip",
        run: function () {
            const menu = document.querySelector(".o_stock_barcode_main_menu");
            if (menu.querySelector(":scope > ul.text-start")) {
                throw new Error("Helper text must be moved into the tooltip");
            }
            const shortcuts = menu.querySelector(".o_barcode_shortcut_buttons");
            if (!shortcuts || !shortcuts.querySelector(".o_barcode_shortcut_button")) {
                throw new Error("Shortcut button must be displayed");
            }
        },
    },
    {
        trigger: '.o_barcode_shortcut_button:contains("Shortcut Tour")',
    },
    {
        // The shortcut opens the ready transfers kanban of the operation type.
        trigger: ".o_kanban_view .o_kanban_renderer",
        extra_trigger: '.breadcrumb-item.active:contains("Shortcut Tour")',
        run: function () {
            // Check only: the kanban of the operation type is opened.
        },
    },
]);

/** @odoo-module **/
/* Copyright (C) 2026 XXP
 * License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl). */

import {MainMenu} from "@stock_barcode/main_menu";
import {patch} from "@web/core/utils/patch";
import {useService} from "@web/core/utils/hooks";

const {onWillStart} = owl;

patch(MainMenu.prototype, "xxp_barcode_picking_shortcut.MainMenu", {
    setup() {
        this._super(...arguments);
        this.orm = useService("orm");
        this.state.shortcuts = [];
        onWillStart(async () => {
            this.state.shortcuts = await this.orm.call(
                "stock.picking.type",
                "get_barcode_shortcuts"
            );
        });
    },

    /**
     * Context for the helper tooltip template: the original helper text hides
     * some hints depending on the user groups, so pass the same flags.
     *
     * @returns {String} JSON string consumed by the tooltip service
     */
    get helpTooltipInfo() {
        return JSON.stringify({
            locationsEnabled: this.locationsEnabled,
            packagesEnabled: this.packagesEnabled,
        });
    },

    /**
     * Shortcuts grouped by pairs: the main menu buttons are laid out as
     * ".row > .col" pairs, which is what the stock_barcode styles target
     * (equal height on desktop, one button per line on mobile).
     *
     * @returns {Array<Array<Object>>} rows of at most two shortcuts
     */
    get shortcutRows() {
        const rows = [];
        for (let i = 0; i < this.state.shortcuts.length; i += 2) {
            rows.push(this.state.shortcuts.slice(i, i + 2));
        }
        return rows;
    },

    /**
     * Open the ready transfers of the given operation type, like a click on
     * its card in the "Operations" kanban does.
     *
     * @param {Number} pickingTypeId id of the stock.picking.type
     * @returns {Promise}
     */
    async onClickShortcut(pickingTypeId) {
        const action = await this.orm.call(
            "stock.picking.type",
            "get_action_picking_tree_ready_kanban",
            [[pickingTypeId]]
        );
        return this.actionService.doAction(action);
    },
});

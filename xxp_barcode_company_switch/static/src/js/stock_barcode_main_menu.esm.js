/** @odoo-module **/

import {BarcodeSwitchCompany} from "./components/barcode_switch_company/barcode_switch_company.esm";
import {MainMenu} from "@stock_barcode/main_menu";
import {patch} from "web.utils";
import {useService} from "@web/core/utils/hooks";

MainMenu.components = {
    ...MainMenu.components,
    BarcodeSwitchCompany,
};

patch(MainMenu.prototype, "xxp_barcode_company_switch.MainMenu", {
    setup() {
        this._super(...arguments);
        // Get the company service
        this.companyService = useService("company");
        // Get the available companies
        this.availableCompanies = this.companyService.availableCompanies;
    },

    /**
     * Check if the company switch should be displayed
     * @returns {Boolean}
     */
    get isDisplayCompanySwitch() {
        return Object.keys(this.availableCompanies).length > 1;
    },
});

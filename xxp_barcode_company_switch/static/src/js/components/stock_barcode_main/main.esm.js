/** @odoo-module **/

import MainComponent from "@stock_barcode/components/main";
import {patch} from "web.utils";
import {useService} from "@web/core/utils/hooks";

patch(MainComponent.prototype, "xxp_barcode_company_switch.main", {
    setup() {
        this._super(...arguments);
        // Get the company service
        this.companyService = useService("company");
        // Get the current company
        this.currentCompany = this.companyService.currentCompany;
        // Get the available companies
        this.availableCompanies = this.companyService.availableCompanies;
    },

    /**
     * Display the company name in the main component
     * @returns {String}
     */
    get displayCompanyName() {
        return this.currentCompany.name;
    },

    /**
     * Check if the company name should be displayed
     * @returns {Boolean}
     */
    get isDisplayCompanyName() {
        return Object.keys(this.availableCompanies).length > 1;
    },
});

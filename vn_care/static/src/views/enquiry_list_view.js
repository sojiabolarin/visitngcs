import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { useEnquiryLiveRefresh } from "@vn_care/live_refresh/live_refresh_hook";

export class EnquiryListController extends listView.Controller {
    setup() {
        super.setup();
        useEnquiryLiveRefresh(() => this.reloadFromServer());
    }

    reloadFromServer() {
        // never reload under the hands of a user who is editing or selecting rows
        if (this.model.root.editedRecord || this.model.root.selection?.length) {
            return;
        }
        return this.model.load();
    }
}

export const enquiryListView = {
    ...listView,
    Controller: EnquiryListController,
};

registry.category("views").add("vn_care_enquiry_list", enquiryListView);

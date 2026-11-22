import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { useEnquiryLiveRefresh } from "@vn_care/live_refresh/live_refresh_hook";

export class EnquiryKanbanController extends kanbanView.Controller {
    setup() {
        super.setup();
        useEnquiryLiveRefresh(() => this.model.load());
    }
}

export const enquiryKanbanView = {
    ...kanbanView,
    Controller: EnquiryKanbanController,
};

registry.category("views").add("vn_care_enquiry_kanban", enquiryKanbanView);

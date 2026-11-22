import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { KeepLast } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { useEnquiryLiveRefresh } from "@vn_care/live_refresh/live_refresh_hook";

const ENQUIRY_ACTION = "vn_care.vn_care_enquiry_action_all";

export class VnCareDashboard extends Component {
    static template = "vn_care.Dashboard";

    props = useProps(standardActionServiceProps);

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.keepLast = new KeepLast();
        this.state = proxy({ data: null });

        onWillStart(() => this.load());
        useEnquiryLiveRefresh((payload) => this.onEnquiriesChanged(payload));
    }

    async load() {
        this.state.data = await this.keepLast.add(
            this.orm.call("vn.care.enquiry", "get_dashboard_data", [])
        );
    }

    async onEnquiriesChanged(payload) {
        await this.load();
        if (payload.event === "new" && this.state.data.is_manager) {
            this.notification.add(_t("A new enquiry has arrived."), { type: "info" });
        }
    }

    /** Width, in percent, of the bar of a category in the breakdown. */
    barWidth(count) {
        const max = Math.max(...this.state.data.categories.map((category) => category.total), 1);
        return Math.round((count / max) * 100);
    }

    /**
     * Opens the list of enquiries behind a figure. The filters are set as
     * search defaults, so the user sees them in the search bar and can remove them.
     */
    openEnquiries(name, filters = {}) {
        const context = {};
        for (const [key, value] of Object.entries(filters)) {
            context[`search_default_${key}`] = value;
        }
        return this.action.doAction(ENQUIRY_ACTION, {
            additionalContext: context,
            props: { displayName: name },
        });
    }

    openTotal() {
        return this.openEnquiries(_t("All Enquiries"));
    }

    openOutstanding() {
        return this.openEnquiries(_t("Outstanding"), { outstanding: 1 });
    }

    openState(state) {
        return this.openEnquiries(state.label, { [`state_${state.key}`]: 1 });
    }

    openDone() {
        return this.openEnquiries(_t("Resolved and Closed"), { state_resolved: 1, state_closed: 1 });
    }

    openCategory(category) {
        return this.openEnquiries(category.name, { category_id: category.id });
    }

    openAgent(agent) {
        return this.openEnquiries(agent.name, { user_id: agent.id, outstanding: 1 });
    }

    openUnassigned() {
        return this.openEnquiries(_t("To Assign"), { unassigned: 1, outstanding: 1 });
    }

    openOverdue() {
        return this.openEnquiries(_t("Overdue Follow-ups"), { activities_overdue: 1 });
    }

    stateCount(key) {
        return this.state.data.states.find((state) => state.key === key)?.count || 0;
    }

    doneCount() {
        return this.stateCount("resolved") + this.stateCount("closed");
    }

    /** The five statuses an enquiry goes through while it is being handled. */
    handlingStates() {
        return this.state.data.states.filter(
            (state) => !["resolved", "closed"].includes(state.key)
        );
    }
}

registry.category("actions").add("vn_care.dashboard", VnCareDashboard);

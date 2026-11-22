import { onMounted, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export const ENQUIRY_CHANGED = "vn_care/enquiry_changed";
const REFRESH_DELAY = 800;

/**
 * Calls `callback` shortly after the server tells that enquiries changed, so
 * that the screen follows new requests and customer replies without a manual
 * page refresh. Several changes in a row give one call.
 *
 * @param {(payload: {event: string, count: number}) => void} callback
 */
export function useEnquiryLiveRefresh(callback) {
    const busService = useService("bus_service");
    let timer = null;
    let unsubscribe = null;
    onMounted(() => {
        unsubscribe = busService.subscribe(ENQUIRY_CHANGED, (payload) => {
            clearTimeout(timer);
            timer = setTimeout(() => callback(payload), REFRESH_DELAY);
        });
        busService.start();
    });
    onWillDestroy(() => {
        clearTimeout(timer);
        unsubscribe?.();
    });
}

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    vn_care_send_acknowledgement = fields.Boolean(
        string='Acknowledge New Enquiries',
        config_parameter='vn_care.send_acknowledgement',
        help="Email the customer a confirmation with the reference number when an enquiry arrives.")
    vn_care_notify_managers = fields.Boolean(
        string='Notify Managers of New Enquiries',
        config_parameter='vn_care.notify_managers')
    group_vn_care_pickup = fields.Boolean(
        string='Agents Pick Up Unassigned Enquiries',
        group='vn_care.vn_care_group_agent',
        implied_group='vn_care.vn_care_group_pickup',
        help="Let agents see the unassigned enquiries and assign one to themselves.")
    vn_care_auto_close_days = fields.Integer(
        string='Close Resolved Enquiries After',
        config_parameter='vn_care.auto_close_days',
        help="Days without a customer reply before a resolved enquiry is closed. 0 never closes.")
    vn_care_webhook_url = fields.Char(
        string='Status Webhook URL',
        config_parameter='vn_care.webhook_url',
        help="Website address that receives each change of status, agent or outcome.")
    vn_care_webhook_secret = fields.Char(
        string='Shared Secret',
        config_parameter='vn_care.webhook_secret',
        help="Signs the webhook calls (HMAC-SHA256) and authenticates the reconciliation call.")
    vn_care_reconcile_url = fields.Char(
        string='Reconciliation URL',
        config_parameter='vn_care.reconcile_url',
        help="Website address listing the enquiries submitted since a given date. "
             "Called every night to pull in anything that was missed.")

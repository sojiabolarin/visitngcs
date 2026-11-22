import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta

import requests

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)

OPEN_STATES = ('new', 'assigned', 'in_progress', 'awaiting_customer', 'awaiting_partner')
DONE_STATES = ('resolved', 'closed')
# Changes of these fields are pushed to the website.
SYNC_FIELDS = ('state', 'user_id', 'outcome', 'booking_reference')
HTTP_TIMEOUT = 10
SYNC_BATCH_SIZE = 50


class VnCareEnquiry(models.Model):
    _name = 'vn.care.enquiry'
    _description = 'Customer Enquiry'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_received desc, id desc'
    _primary_email = 'email'

    name = fields.Char(
        string='Reference', required=True, readonly=True, copy=False, index=True,
        default=lambda self: self.env._("New"))
    submission_id = fields.Char(
        string='Website Submission ID', readonly=True, copy=False,
        help="Identifier of the submission on VisitNigeria.io. It links both systems and "
             "prevents the same submission from being created twice.")
    customer_name = fields.Char(required=True, tracking=True)
    email = fields.Char(string='Email Address', tracking=True, index='btree_not_null')
    email_normalized = fields.Char(compute='_compute_email_normalized', store=True, index='btree_not_null')
    phone = fields.Char(string='Phone Number', tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Customer', index='btree_not_null', ondelete='restrict',
        help="Contact record of the customer. Earlier enquiries of the same customer are found through it.")
    partner_enquiry_count = fields.Integer(string='Customer Enquiries', compute='_compute_partner_enquiry_count')
    category_id = fields.Many2one(
        'vn.care.category', string='Service Category', required=True, index=True,
        ondelete='restrict', tracking=True)
    description = fields.Text(string='Request Details')
    detail_ids = fields.One2many('vn.care.enquiry.detail', 'enquiry_id', string='Category Details')
    date_received = fields.Datetime(
        string='Received On', required=True, default=fields.Datetime.now, index=True, copy=False)
    travel_date = fields.Date(string='Preferred Travel Date')
    state = fields.Selection(
        [
            ('new', 'New'),
            ('assigned', 'Assigned'),
            ('in_progress', 'In Progress'),
            ('awaiting_customer', 'Awaiting Customer'),
            ('awaiting_partner', 'Awaiting Partner'),
            ('resolved', 'Resolved'),
            ('closed', 'Closed'),
        ],
        string='Status', required=True, default='new', copy=False, tracking=True,
        group_expand=True)
    user_id = fields.Many2one(
        'res.users', string='Assigned Agent', index='btree_not_null', copy=False, tracking=True,
        domain=lambda self: [('all_group_ids', 'in', self.env.ref('vn_care.vn_care_group_agent').ids)])
    service_partner_id = fields.Many2one(
        'res.partner', string='Service Partner', index='btree_not_null', tracking=True,
        help="Partner the request was routed to. The booking and the payment happen with the partner.")
    outcome = fields.Selection(
        [
            ('pending', 'Pending'),
            ('converted', 'Converted to Booking'),
            ('not_converted', 'Not Converted'),
        ],
        required=True, default='pending', copy=False, tracking=True)
    booking_reference = fields.Char(
        string='Partner Booking Reference', copy=False, tracking=True,
        help="Reference of the booking at the service partner. Recorded for follow-up only.")

    first_response_date = fields.Datetime(string='First Response On', readonly=True, copy=False)
    resolved_date = fields.Datetime(string='Resolved On', readonly=True, copy=False)
    closed_date = fields.Datetime(string='Closed On', readonly=True, copy=False)
    last_customer_reply_date = fields.Datetime(string='Last Customer Reply', readonly=True, copy=False)
    first_response_hours = fields.Float(
        string='Response Time (hours)', compute='_compute_durations', store=True, aggregator='avg')
    resolution_hours = fields.Float(
        string='Resolution Time (hours)', compute='_compute_durations', store=True, aggregator='avg')
    conversion_rate = fields.Float(
        string='Conversion (%)', compute='_compute_rates', store=True, aggregator='avg',
        help="100 when the enquiry became a booking. Its average over a group is the conversion rate.")
    resolution_rate = fields.Float(
        string='Resolution (%)', compute='_compute_rates', store=True, aggregator='avg',
        help="100 when the enquiry is resolved or closed. Its average over a group is the resolution rate.")
    is_open = fields.Boolean(string='Outstanding', compute='_compute_rates', store=True)

    sync_state = fields.Selection(
        [('synced', 'Synchronised'), ('pending', 'To Send'), ('failed', 'Failed')],
        string='Website Sync', default='synced', required=True, readonly=True, copy=False)
    sync_error = fields.Char(readonly=True, copy=False)
    sync_date = fields.Datetime(string='Last Sent to Website', readonly=True, copy=False)

    _submission_uniq = models.UniqueIndex(
        '(submission_id) WHERE submission_id IS NOT NULL',
        "This website submission already has an enquiry.")
    _sync_pending_idx = models.Index("(id) WHERE sync_state = 'pending'")

    # ------------------------------------------------------------
    # COMPUTES
    # ------------------------------------------------------------

    @api.depends('name', 'customer_name')
    def _compute_display_name(self):
        for enquiry in self:
            enquiry.display_name = ' - '.join(filter(None, [enquiry.name, enquiry.customer_name]))

    @api.depends('email')
    def _compute_email_normalized(self):
        for enquiry in self:
            enquiry.email_normalized = email_normalize(enquiry.email) if enquiry.email else False

    def _compute_partner_enquiry_count(self):
        counts = dict(self._read_group(
            [('partner_id', 'in', self.partner_id.ids)], ['partner_id'], ['__count']))
        for enquiry in self:
            enquiry.partner_enquiry_count = counts.get(enquiry.partner_id, 0)

    @api.depends('date_received', 'first_response_date', 'resolved_date')
    def _compute_durations(self):
        for enquiry in self:
            enquiry.first_response_hours = self._hours_between(
                enquiry.date_received, enquiry.first_response_date)
            enquiry.resolution_hours = self._hours_between(
                enquiry.date_received, enquiry.resolved_date)

    @api.depends('state', 'outcome')
    def _compute_rates(self):
        for enquiry in self:
            enquiry.conversion_rate = 100.0 if enquiry.outcome == 'converted' else 0.0
            enquiry.resolution_rate = 100.0 if enquiry.state in DONE_STATES else 0.0
            enquiry.is_open = enquiry.state in OPEN_STATES

    @api.model
    def _hours_between(self, start, end):
        if not start or not end or end < start:
            return 0.0
        return (end - start).total_seconds() / 3600.0

    @api.constrains('outcome', 'booking_reference')
    def _check_booking_reference(self):
        for enquiry in self:
            if enquiry.booking_reference and enquiry.outcome == 'not_converted':
                raise ValidationError(self.env._(
                    "Enquiry %s has a booking reference, so it cannot be marked as not converted.",
                    enquiry.name))

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        new_label = self.env._("New")
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == new_label:
                vals['name'] = self.env['ir.sequence'].next_by_code('vn.care.enquiry') or new_label
            if vals.get('user_id') and vals.get('state', 'new') == 'new':
                vals['state'] = 'assigned'
        enquiries = super().create(vals_list)
        enquiries.filtered(lambda e: not e.partner_id)._link_customers()
        if not self.env.context.get('vn_care_import'):
            enquiries._send_acknowledgement()
            enquiries._notify_managers_new()
        enquiries._notify_live('new')
        return enquiries

    def write(self, vals):
        if 'user_id' in vals:
            self._check_can_assign(vals['user_id'])
        now = fields.Datetime.now()
        vals = dict(vals)
        if vals.get('booking_reference') and 'outcome' not in vals:
            vals['outcome'] = 'converted'
        state = vals.get('state')
        if state == 'resolved':
            vals.setdefault('resolved_date', now)
        elif state == 'closed':
            vals.setdefault('closed_date', now)
        elif state in OPEN_STATES:
            # reopened: the resolution clock starts again
            vals.update(resolved_date=False, closed_date=False)
        from_website = self.env.context.get('vn_care_from_website')
        if not from_website and any(fname in vals for fname in SYNC_FIELDS):
            vals.update(sync_state='pending', sync_error=False)

        to_assign = self.env['vn.care.enquiry']
        to_unassign = self.env['vn.care.enquiry']
        if 'user_id' in vals and 'state' not in vals:
            if vals['user_id']:
                to_assign = self.filtered(lambda e: e.state == 'new')
            else:
                to_unassign = self.filtered(lambda e: e.state == 'assigned')
        res = super().write(vals)
        if state == 'closed':
            # an enquiry closed without passing by "resolved" still counts as resolved
            for enquiry in self.filtered(lambda e: not e.resolved_date):
                enquiry.resolved_date = enquiry.closed_date
        if to_assign:
            super(VnCareEnquiry, to_assign).write({'state': 'assigned'})
        if to_unassign:
            super(VnCareEnquiry, to_unassign).write({'state': 'new'})
        if vals.get('sync_state') == 'pending':
            self._trigger_sync_cron()
        if any(fname in vals for fname in (*SYNC_FIELDS, 'category_id')):
            self._notify_live('update')
        return res

    def _check_can_assign(self, user_id):
        """Assignment belongs to the managers. An agent may only pick up an
        unassigned enquiry for themselves, when the setting allows it."""
        if self.env.su or self.env.user.has_group('vn_care.vn_care_group_manager'):
            return
        if all(enquiry.user_id.id == user_id for enquiry in self):
            return
        picks_up = (
            user_id == self.env.uid
            and self.env.user.has_group('vn_care.vn_care_group_pickup')
            and not any(enquiry.user_id for enquiry in self)
        )
        if not picks_up:
            raise AccessError(self.env._("Only a Customer Care Manager can assign or reassign an enquiry."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_from_website(self):
        if any(enquiry.submission_id for enquiry in self):
            raise UserError(self.env._(
                "An enquiry received from the website cannot be deleted. Close it instead."))

    # ------------------------------------------------------------
    # CUSTOMER
    # ------------------------------------------------------------

    def _link_customers(self):
        """Attach each enquiry to the contact of its customer, found by email
        or created, so that all enquiries of a customer share one contact."""
        emails = [e.email_normalized for e in self if e.email_normalized]
        partners_by_email = {}
        if emails:
            # sudo - res.partner: agents may not see every contact, the match
            # only uses the email the customer typed on the website.
            partners = self.env['res.partner'].sudo().search(
                [('email_normalized', 'in', emails)], order='id desc')
            partners_by_email = {partner.email_normalized: partner for partner in partners}
        for enquiry in self:
            partner = partners_by_email.get(enquiry.email_normalized)
            if not partner:
                # sudo - res.partner: the contact is created on behalf of the customer
                partner = self.env['res.partner'].sudo().create({
                    'name': enquiry.customer_name,
                    'email': enquiry.email,
                    'phone': enquiry.phone,
                })
                if enquiry.email_normalized:
                    partners_by_email[enquiry.email_normalized] = partner
            enquiry.partner_id = partner.id

    def _get_customer_information(self):
        res = super()._get_customer_information()
        for enquiry in self.filtered('email_normalized'):
            res.setdefault(enquiry.email_normalized, {}).update(
                name=enquiry.customer_name, phone=enquiry.phone)
        return res

    # ------------------------------------------------------------
    # MAIL
    # ------------------------------------------------------------

    def _send_acknowledgement(self):
        if not self.env['ir.config_parameter'].sudo().get_bool('vn_care.send_acknowledgement'):
            return
        template = self.env.ref('vn_care.mail_template_enquiry_acknowledgement', raise_if_not_found=False)
        if not template:
            return
        for enquiry in self.filtered('email_normalized'):
            # sudo - mail.template: sent by the system on receipt, whoever triggered the creation
            enquiry.sudo().message_post_with_source(
                template, message_type='comment', subtype_xmlid='mail.mt_comment',
                author_id=self.env.ref('base.partner_root').id)

    def _notify_managers_new(self):
        if not self.env['ir.config_parameter'].sudo().get_bool('vn_care.notify_managers'):
            return
        managers = self.env.ref('vn_care.vn_care_group_manager').sudo().all_user_ids.filtered(
            lambda user: user.active and not user.share)
        if not managers:
            return
        for enquiry in self.filtered(lambda e: not e.user_id):
            # sudo - mail.message: the notification is posted by the system
            enquiry.sudo().message_notify(
                partner_ids=managers.partner_id.ids,
                subject=self.env._("New enquiry %s", enquiry.name),
                body=self.env._(
                    "New %(category)s enquiry from %(customer)s is waiting to be assigned.",
                    category=enquiry.category_id.name, customer=enquiry.customer_name),
                author_id=self.env.ref('base.partner_root').id,
                email_layout_xmlid='mail.mail_notification_light',
            )

    def message_update(self, msg_dict, update_vals=None):
        """An email from outside the team on an enquiry is the customer (or
        the partner) answering: put the enquiry back in the hands of the agent."""
        author = self.env['res.partner'].browse(msg_dict.get('author_id'))
        from_staff = any(not user.share for user in author.sudo().user_ids)
        if not from_staff:
            now = fields.Datetime.now()
            for enquiry in self:
                vals = {'last_customer_reply_date': now}
                if enquiry.state in ('awaiting_customer', 'awaiting_partner', *DONE_STATES):
                    vals['state'] = 'in_progress' if enquiry.user_id else 'new'
                enquiry.write(vals)
        return super().message_update(msg_dict, update_vals=update_vals)

    def _message_post_after_hook(self, message):
        """The first email an agent sends to the customer stops the response clock."""
        if (
            self
            and not self.first_response_date
            and message.message_type == 'comment'
            and not message.subtype_id.internal
            and message.author_id != self.env.ref('base.partner_root')
            and any(not user.share for user in message.author_id.sudo().user_ids)
        ):
            # sudo - vn.care.enquiry: technical date, set whatever the rights of the author
            self.sudo().first_response_date = fields.Datetime.now()
            if self.state in ('new', 'assigned') and self.user_id:
                self.sudo().state = 'in_progress'
        return super()._message_post_after_hook(message)

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def action_assign_to_me(self):
        self.write({'user_id': self.env.uid})

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_await_customer(self):
        self.write({'state': 'awaiting_customer'})

    def action_await_partner(self):
        self.write({'state': 'awaiting_partner'})

    def action_resolve(self):
        self.write({'state': 'resolved'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reopen(self):
        for enquiry in self:
            enquiry.write({'state': 'in_progress' if enquiry.user_id else 'new'})

    def action_mark_converted(self):
        self.write({'outcome': 'converted'})

    def action_mark_not_converted(self):
        self.write({'outcome': 'not_converted'})

    def action_view_partner_enquiries(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('vn_care.vn_care_enquiry_action')
        action['domain'] = [('partner_id', '=', self.partner_id.id)]
        action['context'] = {}
        action['display_name'] = self.env._("Enquiries of %s", self.customer_name)
        return action

    def action_retry_sync(self):
        self.write({'sync_state': 'pending', 'sync_error': False})
        self._trigger_sync_cron()

    # ------------------------------------------------------------
    # LIVE REFRESH
    # ------------------------------------------------------------

    def _notify_live(self, event):
        """Tell the open dashboards that enquiries changed. The message holds
        no customer data: each client reloads what its user may see."""
        if not self:
            return
        group = self.env.ref('vn_care.vn_care_group_agent', raise_if_not_found=False)
        if group:
            group._bus_send('vn_care/enquiry_changed', {'event': event, 'count': len(self)})

    # ------------------------------------------------------------
    # DASHBOARD
    # ------------------------------------------------------------

    @api.model
    def get_dashboard_data(self):
        """Figures of the overview screen, limited to what the user may read."""
        self.browse().check_access('read')
        by_state = dict(self._read_group([], ['state'], ['__count']))
        states = [
            {'key': key, 'label': label, 'count': by_state.get(key, 0)}
            for key, label in self._fields['state']._description_selection(self.env)
        ]
        open_by_category = dict(self._read_group(
            [('is_open', '=', True)], ['category_id'], ['__count']))
        categories = [
            {
                'id': category.id,
                'name': category.display_name,
                'total': total,
                'open': open_by_category.get(category, 0),
            }
            for category, total in self._read_group(
                [], ['category_id'], ['__count'], order='__count desc, category_id')
        ]
        today = fields.Date.context_today(self)
        overdue = self.search_count([('is_open', '=', True), ('activity_date_deadline', '<', today)])
        unassigned = self.search_count([('is_open', '=', True), ('user_id', '=', False)])
        is_manager = self.env.user.has_group('vn_care.vn_care_group_manager')
        agents = []
        if is_manager:
            agents = [
                {'id': user.id, 'name': user.name, 'open': count}
                for user, count in self._read_group(
                    [('is_open', '=', True), ('user_id', '!=', False)],
                    ['user_id'], ['__count'], order='__count desc, user_id')
            ]
        return {
            'total': sum(by_state.values()),
            'outstanding': sum(by_state.get(key, 0) for key in OPEN_STATES),
            'states': states,
            'categories': categories,
            'agents': agents,
            'overdue': overdue,
            'unassigned': unassigned,
            'is_manager': is_manager,
        }

    # ------------------------------------------------------------
    # WEBSITE: INCOMING
    # ------------------------------------------------------------

    @api.model
    def _api_upsert(self, payload):
        """Create the enquiry of a website submission, once.

        :param dict payload: one submission, see README for the format
        :return: dict describing the enquiry, with ``created`` telling whether
            the call created it or found it already there
        """
        if not isinstance(payload, dict):
            raise ValidationError(self.env._("Each enquiry must be a JSON object."))
        submission_id = str(payload.get('submission_id') or '').strip()
        if not submission_id:
            raise ValidationError(self.env._("submission_id is required."))
        existing = self.search([('submission_id', '=', submission_id)], limit=1)
        if existing:
            return dict(existing._api_format(), created=False)

        customer = payload.get('customer') or {}
        customer_name = (customer.get('name') or payload.get('customer_name') or '').strip()
        category_code = payload.get('category') or payload.get('category_code')
        if not customer_name:
            raise ValidationError(self.env._("customer.name is required."))
        if not category_code:
            raise ValidationError(self.env._("category is required."))
        category = self.env['vn.care.category']._find_or_create_from_code(
            category_code, name=payload.get('category_name'))

        vals = {
            'submission_id': submission_id,
            'customer_name': customer_name,
            'email': (customer.get('email') or payload.get('email') or '').strip() or False,
            'phone': (customer.get('phone') or payload.get('phone') or '').strip() or False,
            'category_id': category.id,
            'description': payload.get('message') or payload.get('details') or False,
            'detail_ids': self._api_prepare_details(payload.get('fields')),
        }
        if payload.get('received_at'):
            vals['date_received'] = self._api_parse_datetime(payload['received_at'])
        if payload.get('travel_date'):
            vals['travel_date'] = fields.Date.to_date(str(payload['travel_date'])[:10])
        if payload.get('status') in dict(self._fields['state'].selection):
            # history imported from the website keeps its status
            vals['state'] = payload['status']
        enquiry = self.with_context(
            vn_care_import=bool(payload.get('historical')),
            mail_create_nosubscribe=True,
        ).create(vals)
        return dict(enquiry._api_format(), created=True)

    @api.model
    def _api_prepare_details(self, details):
        if not details:
            return []
        if isinstance(details, dict):
            details = [{'label': label, 'value': value} for label, value in details.items()]
        commands = []
        for sequence, detail in enumerate(details, start=1):
            label = detail.get('label') or detail.get('name')
            if not label:
                continue
            value = detail.get('value')
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            commands.append(fields.Command.create({
                'sequence': sequence,
                'name': str(label),
                'value': False if value is None else str(value),
            }))
        return commands

    @api.model
    def _api_parse_datetime(self, value):
        """ISO 8601 date and time, with or without offset, to naive UTC."""
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
        except ValueError:
            raise ValidationError(self.env._("Invalid date and time: %s", value)) from None
        if parsed.tzinfo:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed

    def _api_format(self):
        self.ensure_one()
        return {
            'submission_id': self.submission_id,
            'reference': self.name,
            'status': self.state,
            'category': self.category_id.code,
            'assigned_agent': self.user_id.name or None,
            'outcome': self.outcome,
            'booking_reference': self.booking_reference or None,
            'received_at': self.date_received.isoformat(timespec='seconds') + 'Z',
            'updated_at': self.write_date.isoformat(timespec='seconds') + 'Z',
        }

    # ------------------------------------------------------------
    # WEBSITE: OUTGOING
    # ------------------------------------------------------------

    def _trigger_sync_cron(self):
        cron = self.env.ref('vn_care.ir_cron_vn_care_push_sync', raise_if_not_found=False)
        if cron:
            cron._trigger()

    @api.model
    def _get_webhook_config(self):
        Parameter = self.env['ir.config_parameter'].sudo()
        return Parameter.get_str('vn_care.webhook_url'), Parameter.get_str('vn_care.webhook_secret')

    @api.model
    def _sign(self, secret, body):
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    @api.model
    def _cron_push_sync(self):
        """Send the pending changes to the website, one call per enquiry."""
        url, secret = self._get_webhook_config()
        pending = self.search(
            [('sync_state', '=', 'pending'), ('submission_id', '!=', False)],
            limit=SYNC_BATCH_SIZE, order='write_date, id')
        local_only = self.search([('sync_state', '=', 'pending'), ('submission_id', '=', False)])
        local_only.with_context(vn_care_from_website=True).write({'sync_state': 'synced'})
        if not url:
            # nothing to call yet: keep them pending until the webhook is configured
            return
        for enquiry in pending:
            enquiry._push_to_website(url, secret)
        if len(pending) == SYNC_BATCH_SIZE:
            self._trigger_sync_cron()

    def _push_to_website(self, url, secret):
        self.ensure_one()
        body = json.dumps(self._api_format(), separators=(',', ':')).encode()
        headers = {
            'Content-Type': 'application/json',
            'X-VN-Care-Event': 'enquiry.updated',
            'X-VN-Care-Signature': self._sign(secret, body),
        }
        vals = {'sync_date': fields.Datetime.now()}
        try:
            response = requests.post(url, data=body, headers=headers, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            vals.update(sync_state='synced', sync_error=False)
        except requests.RequestException as error:
            _logger.warning("VN Care: could not send %s to the website: %s", self.name, error)
            vals.update(sync_state='failed', sync_error=str(error)[:250])
        self.with_context(vn_care_from_website=True).write(vals)

    @api.model
    def _cron_retry_failed_sync(self):
        failed = self.search([('sync_state', '=', 'failed')])
        if failed:
            failed.with_context(vn_care_from_website=True).write({'sync_state': 'pending'})
            self._trigger_sync_cron()

    @api.model
    def _cron_reconcile(self):
        """Ask the website for the submissions of the last days and create
        the ones that never arrived."""
        Parameter = self.env['ir.config_parameter'].sudo()
        url = Parameter.get_str('vn_care.reconcile_url')
        if not url:
            return
        secret = Parameter.get_str('vn_care.webhook_secret')
        since = fields.Datetime.now() - timedelta(days=2)
        try:
            response = requests.get(
                url, params={'since': since.isoformat() + 'Z'},
                headers={'Authorization': f'Bearer {secret}'}, timeout=HTTP_TIMEOUT * 3)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            _logger.warning("VN Care: reconciliation with the website failed: %s", error)
            return
        submissions = data.get('enquiries', []) if isinstance(data, dict) else data
        created = 0
        for submission in submissions:
            try:
                with self.env.cr.savepoint():
                    created += self._api_upsert(submission)['created']
            except (ValidationError, UserError) as error:
                _logger.warning("VN Care: reconciliation skipped a submission: %s", error)
        if created:
            _logger.info("VN Care: reconciliation created %s missing enquiries", created)

    # ------------------------------------------------------------
    # AUTOMATION
    # ------------------------------------------------------------

    @api.model
    def _cron_auto_close(self):
        days = self.env['ir.config_parameter'].sudo().get_int('vn_care.auto_close_days')
        if days <= 0:
            return
        limit_date = fields.Datetime.now() - timedelta(days=days)
        domain = Domain('state', '=', 'resolved') & Domain('resolved_date', '<=', limit_date)
        self.search(domain).write({'state': 'closed'})

import json
import logging

import requests

from odoo import api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10


class VnCareMessageSync(models.Model):
    """One line per message of the conversation exchanged with the website:
    sent to it so that the customer reads it in their account, or received
    from it when the customer answers there."""

    _name = 'vn.care.message.sync'
    _description = 'Customer Care Message Exchanged with the Website'
    _order = 'id desc'

    enquiry_id = fields.Many2one('vn.care.enquiry', required=True, index=True, ondelete='cascade')
    message_id = fields.Many2one('mail.message', required=True, index=True, ondelete='cascade')
    direction = fields.Selection(
        [('out', 'Sent to Website'), ('in', 'Received from Website')], required=True)
    external_id = fields.Char(
        string='Website Message ID',
        help="Identifier of the message on the website. A message received twice is stored once.")
    state = fields.Selection(
        [('pending', 'To Send'), ('synced', 'Synchronised'), ('failed', 'Failed')],
        required=True, default='pending')
    error = fields.Char()
    sync_date = fields.Datetime(string='Sent On')

    _external_uniq = models.UniqueIndex(
        '(enquiry_id, external_id) WHERE external_id IS NOT NULL',
        "This website message is already on the enquiry.")
    _pending_idx = models.Index("(id) WHERE state = 'pending'")

    def _prepare_payload(self):
        self.ensure_one()
        message = self.message_id
        enquiry = self.enquiry_id
        if message.author_id == enquiry.partner_id:
            author_type = 'customer'
        elif any(not user.share for user in message.author_id.user_ids):
            author_type = 'agent'
        else:
            author_type = 'system'
        return {
            'submission_id': enquiry.submission_id,
            'reference': enquiry.name,
            'message': {
                'id': message.id,
                'author_type': author_type,
                'author_name': message.author_id.name or message.email_from or None,
                'subject': message.subject or None,
                'body_html': str(message.body or ''),
                'body_text': html2plaintext(message.body or ''),
                'attachments': message.attachment_ids.mapped('name'),
                'sent_at': message.date.isoformat(timespec='seconds') + 'Z',
            },
        }

    def _push_to_website(self, url, secret):
        self.ensure_one()
        body = json.dumps(self._prepare_payload(), separators=(',', ':')).encode()
        headers = {
            'Content-Type': 'application/json',
            'X-VN-Care-Event': 'enquiry.message',
            'X-VN-Care-Signature': self.env['vn.care.enquiry']._sign(secret, body),
        }
        vals = {'sync_date': fields.Datetime.now()}
        try:
            response = requests.post(url, data=body, headers=headers, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            vals.update(state='synced', error=False)
        except requests.RequestException as error:
            _logger.warning(
                "VN Care: could not send a message of %s to the website: %s",
                self.enquiry_id.name, error)
            vals.update(state='failed', error=str(error)[:250])
        self.write(vals)

    @api.model
    def _push_pending(self, url, secret, limit):
        """Send the waiting messages, oldest first so the website receives
        each conversation in order. Return how many were handled."""
        pending = self.search([('state', '=', 'pending'), ('direction', '=', 'out')], limit=limit, order='id')
        for sync in pending:
            sync._push_to_website(url, secret)
        return len(pending)

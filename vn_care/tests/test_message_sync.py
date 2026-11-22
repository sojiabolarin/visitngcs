import json

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.vn_care.models import vn_care_message_sync
from odoo.addons.vn_care.tests.common import VnCareCommon


@tagged('post_install', '-at_install')
class TestMessageSync(VnCareCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enquiry.user_id = cls.agent
        cls.Sync = cls.env['vn.care.message.sync'].sudo()

    def test_agent_reply_goes_to_website(self):
        enquiry = self.enquiry.with_user(self.agent)
        enquiry.message_post(body='Internal remark', subtype_xmlid='mail.mt_note')
        self.assertFalse(self.Sync.search([('enquiry_id', '=', self.enquiry.id)]), "notes never leave")
        message = enquiry.message_post(
            body='Hello Ada, two rooms are available.', message_type='comment',
            subtype_xmlid='mail.mt_comment', partner_ids=self.enquiry.partner_id.ids)
        sync = self.Sync.search([('enquiry_id', '=', self.enquiry.id)])
        self.assertEqual(sync.message_id, message)
        self.assertEqual((sync.direction, sync.state), ('out', 'pending'))

        self.env['ir.config_parameter'].sudo().set_str('vn_care.webhook_url', 'https://website.test/hook')
        self.env['ir.config_parameter'].sudo().set_str('vn_care.webhook_secret', 's3cret')
        calls = []

        class Response:
            def raise_for_status(self):
                return None

        def post(url, data=None, headers=None, timeout=None):
            calls.append((data, headers))
            return Response()

        self.patch(vn_care_message_sync.requests, 'post', post)
        self.Sync.sudo()._push_pending('https://website.test/hook', 's3cret', 10)
        self.assertEqual(sync.state, 'synced')
        body, headers = calls[0]
        payload = json.loads(body)
        self.assertEqual(headers['X-VN-Care-Event'], 'enquiry.message')
        self.assertEqual(headers['X-VN-Care-Signature'], self.env['vn.care.enquiry']._sign('s3cret', body))
        self.assertEqual(payload['submission_id'], 'sub-common')
        self.assertEqual(payload['message']['author_type'], 'agent')
        self.assertIn('two rooms are available', payload['message']['body_text'])

    def test_customer_message_from_website(self):
        self.enquiry.action_await_customer()
        enquiry = self.enquiry.sudo()
        result = enquiry._api_post_customer_message({'message_id': 'wm-1', 'body': 'Yes please, book them.'})
        self.assertTrue(result['created'])
        self.assertEqual(self.enquiry.state, 'in_progress', "an answer puts the enquiry back with the agent")
        self.assertTrue(self.enquiry.last_customer_reply_date)
        sync = self.Sync.search([('enquiry_id', '=', self.enquiry.id)])
        self.assertEqual((sync.direction, sync.state), ('in', 'synced'), "it is not sent back to the website")
        self.assertEqual(sync.message_id.author_id, self.enquiry.partner_id)
        self.assertIn(self.agent.partner_id, sync.message_id.notified_partner_ids)

        again = enquiry._api_post_customer_message({'message_id': 'wm-1', 'body': 'Yes please, book them.'})
        self.assertFalse(again['created'])
        self.assertEqual(len(self.Sync.search([('enquiry_id', '=', self.enquiry.id)])), 1)
        with self.assertRaises(ValidationError):
            enquiry._api_post_customer_message({'message_id': 'wm-2'})

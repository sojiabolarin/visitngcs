from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.vn_care.models import vn_care_enquiry
from odoo.addons.vn_care.tests.common import VnCareCommon


@tagged('post_install', '-at_install')
class TestEnquiry(VnCareCommon):

    def test_reference_and_customer(self):
        self.assertTrue(self.enquiry.name.startswith('VN-ENQ-'))
        self.assertEqual(self.enquiry.state, 'new')
        self.assertEqual(self.enquiry.partner_id.email_normalized, 'ada.obi@example.com')
        second = self.env['vn.care.enquiry'].create({
            'customer_name': 'Ada Obi',
            'email': 'Ada.Obi@example.com',
            'category_id': self.category.id,
        })
        self.assertEqual(second.partner_id, self.enquiry.partner_id, "a returning customer keeps one contact")
        self.assertEqual(second.partner_enquiry_count, 2)

    def test_assignment_moves_status(self):
        self.enquiry.with_user(self.manager).user_id = self.agent
        self.assertEqual(self.enquiry.state, 'assigned')
        self.assertIn(self.agent.partner_id, self.enquiry.message_partner_ids)
        self.enquiry.with_user(self.manager).user_id = False
        self.assertEqual(self.enquiry.state, 'new')

    def test_status_dates_and_rates(self):
        self.enquiry.user_id = self.agent
        self.enquiry.action_start()
        self.enquiry.action_resolve()
        self.assertTrue(self.enquiry.resolved_date)
        self.assertEqual(self.enquiry.resolution_rate, 100)
        self.assertFalse(self.enquiry.is_open)
        self.enquiry.action_reopen()
        self.assertEqual(self.enquiry.state, 'in_progress')
        self.assertFalse(self.enquiry.resolved_date)
        self.enquiry.booking_reference = 'WKN-123'
        self.assertEqual(self.enquiry.outcome, 'converted')
        self.assertEqual(self.enquiry.conversion_rate, 100)

    def test_first_response(self):
        self.enquiry.user_id = self.agent
        enquiry = self.enquiry.with_user(self.agent)
        enquiry.message_post(body='internal', subtype_xmlid='mail.mt_note')
        self.assertFalse(self.enquiry.first_response_date, "an internal note is not a response")
        enquiry.message_post(
            body='Hello Ada', message_type='comment', subtype_xmlid='mail.mt_comment',
            partner_ids=self.enquiry.partner_id.ids)
        self.assertTrue(self.enquiry.first_response_date)
        self.assertEqual(self.enquiry.state, 'in_progress')

    def test_customer_reply_reopens(self):
        self.enquiry.user_id = self.agent
        self.enquiry.action_await_customer()
        self.enquiry.message_update({'author_id': self.enquiry.partner_id.id})
        self.assertEqual(self.enquiry.state, 'in_progress')
        self.assertTrue(self.enquiry.last_customer_reply_date)
        self.enquiry.action_resolve()
        self.enquiry.action_close()
        self.enquiry.message_update({'author_id': self.enquiry.partner_id.id})
        self.assertEqual(self.enquiry.state, 'in_progress', "a reply reopens a closed enquiry")
        # an email of a colleague changes nothing
        self.enquiry.action_await_customer()
        self.enquiry.message_update({'author_id': self.manager.partner_id.id})
        self.assertEqual(self.enquiry.state, 'awaiting_customer')

    def test_auto_close(self):
        self.env['ir.config_parameter'].sudo().set_int('vn_care.auto_close_days', 7)
        self.enquiry.action_resolve()
        self.env['vn.care.enquiry']._cron_auto_close()
        self.assertEqual(self.enquiry.state, 'resolved')
        self.enquiry.resolved_date = fields.Datetime.now() - timedelta(days=8)
        self.env['vn.care.enquiry']._cron_auto_close()
        self.assertEqual(self.enquiry.state, 'closed')

    def test_website_enquiry_is_kept(self):
        with self.assertRaises(UserError):
            self.enquiry.unlink()

    def test_sync_marks_and_pushes(self):
        self.assertEqual(self.enquiry.sync_state, 'synced')
        self.enquiry.user_id = self.agent
        self.assertEqual(self.enquiry.sync_state, 'pending')
        self.env['ir.config_parameter'].sudo().set_str('vn_care.webhook_url', 'https://website.test/hook')
        self.env['ir.config_parameter'].sudo().set_str('vn_care.webhook_secret', 's3cret')
        calls = []

        class Response:
            def raise_for_status(self):
                return None

        def post(url, data=None, headers=None, timeout=None):
            calls.append((url, data, headers))
            return Response()

        self.patch(type(self.env['vn.care.enquiry']), '_trigger_sync_cron', lambda self: None)
        self.patch(vn_care_enquiry.requests, 'post', post)
        self.env['vn.care.enquiry']._cron_push_sync()
        self.assertEqual(self.enquiry.sync_state, 'synced')
        self.assertEqual(len(calls), 1)
        url, body, headers = calls[0]
        self.assertEqual(url, 'https://website.test/hook')
        self.assertIn(b'"status":"assigned"', body)
        self.assertEqual(
            headers['X-VN-Care-Signature'], self.env['vn.care.enquiry']._sign('s3cret', body))

    def test_dashboard(self):
        self.enquiry.user_id = self.agent
        self.env['vn.care.enquiry'].create({
            'customer_name': 'Marcus Reid', 'category_id': self.category.id,
        })
        self.env.invalidate_all()
        agent_data = self.env['vn.care.enquiry'].with_user(self.agent).get_dashboard_data()
        self.assertEqual(agent_data['total'], 1, "an agent counts only their own enquiries")
        self.assertFalse(agent_data['agents'])
        manager_data = self.env['vn.care.enquiry'].with_user(self.manager).get_dashboard_data()
        self.assertGreaterEqual(manager_data['total'], 2)
        self.assertGreaterEqual(manager_data['unassigned'], 1)
        self.assertTrue(manager_data['is_manager'])
        self.assertEqual(
            sum(state['count'] for state in manager_data['states']), manager_data['total'])

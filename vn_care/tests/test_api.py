from datetime import timedelta

from odoo import Command, fields
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].set_bool('vn_care.send_acknowledgement', False)
        cls.env['ir.config_parameter'].set_bool('vn_care.notify_managers', False)
        cls.api_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Website Integration',
            'login': 'website@care.test',
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id, cls.env.ref('vn_care.vn_care_group_api').id])],
        })
        cls.plain_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Somebody', 'login': 'somebody@care.test',
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })
        expiration = fields.Datetime.now() + timedelta(days=1)
        ApiKeys = cls.env['res.users.apikeys']
        cls.api_key = ApiKeys.with_user(cls.api_user)._generate('vn_care', 'website', expiration)
        cls.plain_key = ApiKeys.with_user(cls.plain_user)._generate('vn_care', 'other', expiration)
        cls.payload = {
            'submission_id': 'web-1001',
            'category': 'hotels',
            'customer': {'name': 'Ada Obi', 'email': 'ada.obi@example.com', 'phone': '+2348000000001'},
            'message': 'Two rooms in Lagos',
            'travel_date': '2026-12-20',
            'received_at': '2026-11-20T09:30:00+01:00',
            'fields': {'City': 'Lagos', 'Guests': 4},
        }

    def _post(self, payload, key=None):
        return self.url_open(
            '/vn_care/api/v1/enquiries', json=payload,
            headers={'Authorization': f'Bearer {key or self.api_key}'})

    def test_create_is_idempotent(self):
        response = self._post(self.payload)
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertTrue(data['created'])
        self.assertTrue(data['reference'].startswith('VN-ENQ-'))
        enquiry = self.env['vn.care.enquiry'].search([('submission_id', '=', 'web-1001')])
        self.assertEqual(len(enquiry), 1)
        self.assertEqual(enquiry.customer_name, 'Ada Obi')
        self.assertEqual(enquiry.category_id.code, 'hotels')
        self.assertEqual(str(enquiry.date_received), '2026-11-20 08:30:00')
        self.assertEqual(enquiry.detail_ids.mapped('name'), ['City', 'Guests'])
        self.assertEqual(enquiry.sync_state, 'synced')

        again = self._post(self.payload)
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()['created'])
        self.assertEqual(again.json()['reference'], data['reference'])
        self.assertEqual(self.env['vn.care.enquiry'].search_count([('submission_id', '=', 'web-1001')]), 1)

        status = self.url_open(
            '/vn_care/api/v1/enquiries/web-1001', headers={'Authorization': f'Bearer {self.api_key}'})
        self.assertEqual(status.json()['status'], 'new')

    def test_new_category_is_created(self):
        response = self._post(dict(self.payload, submission_id='web-1002', category='Car Rental'))
        self.assertEqual(response.status_code, 201, response.text)
        category = self.env['vn.care.category'].search([('code', '=', 'car_rental')])
        self.assertTrue(category.needs_review)
        self.assertEqual(category.name, 'Car Rental')

    def test_batch_and_validation(self):
        response = self._post({'enquiries': [
            dict(self.payload, submission_id='web-2001', historical=True, status='closed'),
            {'submission_id': 'web-2002'},
        ]})
        self.assertEqual(response.status_code, 207)
        results = response.json()['results']
        self.assertTrue(results[0]['created'])
        self.assertIn('error', results[1])
        self.assertEqual(
            self.env['vn.care.enquiry'].search([('submission_id', '=', 'web-2001')]).state, 'closed')
        single = self._post({'category': 'hotels'})
        self.assertEqual(single.status_code, 422)

    @mute_logger('odoo.http')
    def test_authentication(self):
        response = self.url_open('/vn_care/api/v1/enquiries', json=self.payload)
        self.assertEqual(response.status_code, 401)
        response = self._post(self.payload, key='not-a-key')
        self.assertEqual(response.status_code, 401)
        response = self._post(self.payload, key=self.plain_key)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.env['vn.care.enquiry'].search([('submission_id', '=', 'web-1001')]))

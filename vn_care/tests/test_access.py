from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.vn_care.tests.common import VnCareCommon


@tagged('post_install', '-at_install')
class TestAccess(VnCareCommon):

    def test_agent_sees_own_enquiries_only(self):
        Enquiry = self.env['vn.care.enquiry']
        self.env.invalidate_all()
        self.assertNotIn(self.enquiry, Enquiry.with_user(self.agent).search([]))
        self.enquiry.user_id = self.agent
        self.env.invalidate_all()
        self.assertIn(self.enquiry, Enquiry.with_user(self.agent).search([]))
        self.assertNotIn(self.enquiry, Enquiry.with_user(self.other_agent).search([]))
        with self.assertRaises(AccessError):
            self.enquiry.with_user(self.other_agent).read(['customer_name'])
        self.assertIn(self.enquiry, Enquiry.with_user(self.manager).search([]))

    def test_agent_cannot_reassign(self):
        self.enquiry.user_id = self.agent
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.enquiry.with_user(self.agent).user_id = self.other_agent
        self.enquiry.with_user(self.agent).action_start()
        self.assertEqual(self.enquiry.state, 'in_progress')
        self.enquiry.with_user(self.manager).user_id = self.other_agent
        self.assertEqual(self.enquiry.user_id, self.other_agent)

    def test_pickup(self):
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.enquiry.with_user(self.agent).action_assign_to_me()
        self.env.ref('vn_care.vn_care_group_agent').sudo().implied_ids |= self.env.ref('vn_care.vn_care_group_pickup')
        self.env.invalidate_all()
        self.enquiry.with_user(self.agent).action_assign_to_me()
        self.assertEqual(self.enquiry.user_id, self.agent)
        self.assertEqual(self.enquiry.state, 'assigned')

    def test_agent_cannot_create_or_delete(self):
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.env['vn.care.enquiry'].with_user(self.agent).create({
                'customer_name': 'X', 'category_id': self.category.id,
            })
        self.enquiry.user_id = self.agent
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            self.enquiry.with_user(self.agent).unlink()
        with self.assertRaises(AccessError):
            self.category.with_user(self.manager).name = 'Renamed'

    def test_team_management(self):
        Users = self.env['res.users']
        with self.assertRaises(AccessError):
            self.agent.with_user(self.manager)._vn_care_set_level('manager')
        self.agent.with_user(self.management)._vn_care_set_level('manager')
        self.assertEqual(self.agent.vn_care_level, 'manager')
        wizard = self.env['vn.care.user.invite'].with_user(self.management).with_context(
            no_reset_password=True).create({'name': 'New Agent', 'email': 'new.agent@care.test', 'level': 'agent'})
        wizard.action_apply()
        user = Users.sudo().search([('login', '=', 'new.agent@care.test')])
        self.assertEqual(user.vn_care_level, 'agent')
        self.assertFalse(user.has_group('base.group_system'))
        self.assertFalse(user.has_group('base.group_erp_manager'))
        user.with_user(self.management).action_vn_care_deactivate()
        self.assertFalse(user.active)
        with self.assertRaises(AccessError):
            self.env.ref('base.user_admin').with_user(self.management).action_vn_care_deactivate()

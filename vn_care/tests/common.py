from odoo import Command

from odoo.addons.base.tests.common import BaseCommon


class VnCareCommon(BaseCommon):
    # the tests set records up as management, and act as the other levels with with_user
    _test_user_groups = ('base.group_user', 'vn_care.vn_care_group_admin')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_bool('vn_care.send_acknowledgement', False)
        cls.env['ir.config_parameter'].sudo().set_bool('vn_care.notify_managers', False)
        cls.agent = cls._create_care_user('agent@care.test', 'vn_care.vn_care_group_agent')
        cls.other_agent = cls._create_care_user('agent2@care.test', 'vn_care.vn_care_group_agent')
        cls.manager = cls._create_care_user('manager@care.test', 'vn_care.vn_care_group_manager')
        cls.management = cls._create_care_user('management@care.test', 'vn_care.vn_care_group_admin')
        cls.category = cls.env.ref('vn_care.vn_care_category_hotels')
        cls.enquiry = cls.env['vn.care.enquiry'].create({
            'customer_name': 'Ada Obi',
            'email': 'ada.obi@example.com',
            'category_id': cls.category.id,
            'description': 'Two rooms in Lagos',
            'submission_id': 'sub-common',
        })

    @classmethod
    def _create_care_user(cls, login, group_xmlid):
        return cls.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': login.split('@')[0].title(),
            'login': login,
            'email': login,
            'group_ids': [Command.set([cls.env.ref('base.group_user').id, cls.env.ref(group_xmlid).id])],
        })

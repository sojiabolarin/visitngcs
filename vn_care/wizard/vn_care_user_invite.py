from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import email_normalize

from odoo.addons.vn_care.models.res_users import CARE_LEVELS


class VnCareUserInvite(models.TransientModel):
    _name = 'vn.care.user.invite'
    _description = 'Add or Update a Customer Care User'

    user_id = fields.Many2one('res.users', string='Existing User', readonly=True)
    name = fields.Char(string='Full Name')
    email = fields.Char(string='Email Address', help="Used as the login and for the invitation.")
    level = fields.Selection(CARE_LEVELS, string='Access Level', required=True, default='agent')

    def action_apply(self):
        self.ensure_one()
        Users = self.env['res.users']
        if self.user_id:
            self.user_id._vn_care_set_level(self.level)
            return {'type': 'ir.actions.act_window_close'}

        Users._vn_care_check_manageable()
        email = email_normalize(self.email or '')
        if not self.name or not email:
            raise UserError(self.env._("Enter the full name and a valid email address."))
        # sudo - res.users: management adds care users without holding the
        # general right to administer users
        existing = Users.sudo().with_context(active_test=False).search([('login', '=', email)], limit=1)
        if existing:
            existing._vn_care_check_manageable()
            existing.sudo().active = True
            existing._vn_care_set_level(self.level)
        else:
            user = Users.sudo().create({
                'name': self.name,
                'login': email,
                'email': email,
                'group_ids': [fields.Command.set(self.env.ref('base.group_user').ids)],
            })
            user._vn_care_set_level(self.level)
        return {'type': 'ir.actions.act_window_close'}

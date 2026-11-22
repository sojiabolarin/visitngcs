from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

CARE_LEVELS = [
    ('agent', 'Customer Care Agent'),
    ('manager', 'Customer Care Manager'),
    ('admin', 'Super Admin / Management'),
]
LEVEL_GROUPS = {
    'agent': 'vn_care.vn_care_group_agent',
    'manager': 'vn_care.vn_care_group_manager',
    'admin': 'vn_care.vn_care_group_admin',
}


class ResUsers(models.Model):
    _inherit = 'res.users'

    vn_care_level = fields.Selection(
        CARE_LEVELS, string='Customer Care Level', compute='_compute_vn_care_level')
    vn_care_open_count = fields.Integer(
        string='Open Enquiries', compute='_compute_vn_care_open_count')

    @api.depends('group_ids')
    def _compute_vn_care_level(self):
        for user in self:
            user.vn_care_level = next(
                (level for level in ('admin', 'manager', 'agent') if user.has_group(LEVEL_GROUPS[level])),
                False)

    def _compute_vn_care_open_count(self):
        counts = dict(self.env['vn.care.enquiry']._read_group(
            [('user_id', 'in', self.ids), ('is_open', '=', True)], ['user_id'], ['__count']))
        for user in self:
            user.vn_care_open_count = counts.get(user, 0)

    def _vn_care_check_manageable(self):
        """Management handles the care team only: never the technical
        administrators, and never from another group than management."""
        if not self.env.user.has_group('vn_care.vn_care_group_admin'):
            raise AccessError(self.env._("Only Management can manage the Customer Care team."))
        if self.env.user.has_group('base.group_system'):
            return
        for user in self:
            if user.has_group('base.group_system'):
                raise AccessError(self.env._(
                    "%s is a technical administrator and is managed by the technical team.", user.name))

    def _vn_care_set_level(self, level):
        """Give the users one care level and nothing else of the care app."""
        self._vn_care_check_manageable()
        care_groups = self.env['res.groups']
        for xmlid in LEVEL_GROUPS.values():
            care_groups |= self.env.ref(xmlid)
        commands = [fields.Command.unlink(group.id) for group in care_groups]
        if level:
            commands.append(fields.Command.link(self.env.ref(LEVEL_GROUPS[level]).id))
        # sudo - res.users: management may change the care level, and only that
        self.sudo().write({'group_ids': commands})

    def action_vn_care_change_level(self):
        self.ensure_one()
        self._vn_care_check_manageable()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Change Level"),
            'res_model': 'vn.care.user.invite',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_user_id': self.id, 'default_level': self.vn_care_level or 'agent'},
        }

    def action_vn_care_deactivate(self):
        self._vn_care_check_manageable()
        if self.env.user in self:
            raise UserError(self.env._("You cannot deactivate your own account."))
        open_enquiries = self.env['vn.care.enquiry'].sudo().search_count(
            [('user_id', 'in', self.ids), ('is_open', '=', True)])
        if open_enquiries:
            raise UserError(self.env._(
                "Reassign the %s open enquiries of this account before deactivating it.", open_enquiries))
        # sudo - res.users: see _vn_care_set_level
        self.sudo().write({'active': False})

    def action_vn_care_reactivate(self):
        self._vn_care_check_manageable()
        # sudo - res.users: see _vn_care_set_level
        self.sudo().write({'active': True})

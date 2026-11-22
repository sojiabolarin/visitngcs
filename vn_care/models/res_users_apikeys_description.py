from odoo import fields, models


class ResUsersApikeysDescription(models.TransientModel):
    _inherit = 'res.users.apikeys.description'

    scope = fields.Selection(
        selection_add=[('vn_care', 'Customer Care API')],
        ondelete={'vn_care': 'cascade'})

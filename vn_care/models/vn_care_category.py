from odoo import api, fields, models


class VnCareCategory(models.Model):
    _name = 'vn.care.category'
    _description = 'Customer Care Service Category'
    _order = 'sequence, name, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True, copy=False, index=True,
        help="Technical code the website sends with each enquiry of this category.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')
    description = fields.Text(translate=True)
    needs_review = fields.Boolean(
        string='To Review', copy=False,
        help="Set when the category was created automatically from a code the website sent "
             "for the first time. Check its name, then clear the flag.")
    enquiry_ids = fields.One2many('vn.care.enquiry', 'category_id', string='Enquiries')
    enquiry_count = fields.Integer(compute='_compute_enquiry_count')

    _code_uniq = models.Constraint('UNIQUE(code)', "A service category already uses this code.")

    def _compute_enquiry_count(self):
        counts = dict(self.env['vn.care.enquiry']._read_group(
            [('category_id', 'in', self.ids)], ['category_id'], ['__count']))
        for category in self:
            category.enquiry_count = counts.get(category, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code'):
                vals['code'] = self._normalize_code(vals['code'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('code'):
            vals = dict(vals, code=self._normalize_code(vals['code']))
        return super().write(vals)

    def action_mark_reviewed(self):
        self.needs_review = False

    @api.model
    def _normalize_code(self, code):
        return '_'.join(str(code).strip().lower().replace('-', ' ').split())

    @api.model
    def _find_or_create_from_code(self, code, name=None):
        """Return the category matching the code sent by the website.

        A code seen for the first time creates its category, flagged for
        review, so that a service added on the website needs no development.
        """
        code = self._normalize_code(code)
        category = self.with_context(active_test=False).search([('code', '=', code)], limit=1)
        if not category:
            category = self.create({
                'name': name or code.replace('_', ' ').title(),
                'code': code,
                'needs_review': True,
            })
        return category

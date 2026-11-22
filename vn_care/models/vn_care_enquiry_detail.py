from odoo import fields, models


class VnCareEnquiryDetail(models.Model):
    _name = 'vn.care.enquiry.detail'
    _description = 'Customer Care Enquiry Detail'
    _order = 'sequence, id'

    enquiry_id = fields.Many2one('vn.care.enquiry', required=True, index=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Field', required=True)
    value = fields.Char()

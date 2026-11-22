import logging

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

API_GROUP = 'vn_care.vn_care_group_api'
MAX_BATCH = 500


class VnCareApi(http.Controller):
    """Endpoints the website calls. Authentication is an Odoo API key of scope
    "Customer Care API" sent as ``Authorization: Bearer <key>``; the key must
    belong to a user of the "Website Integration (API)" group. Such a key
    opens these endpoints only, not the rest of the Odoo API."""

    def _check_api_user(self):
        if not request.env.user.has_group(API_GROUP):
            raise AccessError(request.env._("This API key is not allowed to use the Customer Care API."))

    def _error(self, message, status):
        return request.make_json_response({'error': message}, status=status)

    @http.route(
        '/vn_care/api/v1/enquiries', type='http', auth='bearer', bearer_scope='vn_care',
        methods=['POST'], csrf=False, readonly=False)
    def create_enquiries(self):
        """Create one enquiry (a JSON object) or several (``{"enquiries": [...]}``).
        A submission that already exists is returned as it stands, so the
        website can retry a call safely."""
        self._check_api_user()
        try:
            data = request.get_json_data()
        except ValueError:
            return self._error("The body must be valid JSON.", 400)
        batch = isinstance(data, dict) and isinstance(data.get('enquiries'), list)
        submissions = data['enquiries'] if batch else [data]
        if len(submissions) > MAX_BATCH:
            return self._error(f"Send at most {MAX_BATCH} enquiries per call.", 413)

        # sudo - vn.care.enquiry: the integration account has no access to the
        # dashboard; its only right is to hand submissions over, checked above.
        Enquiry = request.env['vn.care.enquiry'].sudo()
        results = []
        failed = False
        for submission in submissions:
            try:
                with request.env.cr.savepoint():
                    results.append(Enquiry._api_upsert(submission))
            except (ValidationError, UserError) as error:
                failed = True
                results.append({
                    'submission_id': submission.get('submission_id') if isinstance(submission, dict) else None,
                    'error': str(error),
                })
        if not batch:
            result = results[0]
            if failed:
                return self._error(result['error'], 422)
            return request.make_json_response(result, status=201 if result['created'] else 200)
        return request.make_json_response({'results': results}, status=207 if failed else 200)

    @http.route(
        '/vn_care/api/v1/enquiries/<string:submission_id>', type='http', auth='bearer',
        bearer_scope='vn_care', methods=['GET'], readonly=True)
    def get_enquiry(self, submission_id):
        self._check_api_user()
        # sudo - vn.care.enquiry: see create_enquiries
        enquiry = request.env['vn.care.enquiry'].sudo().search(
            [('submission_id', '=', submission_id)], limit=1)
        if not enquiry:
            return self._error("No enquiry for this submission.", 404)
        return request.make_json_response(enquiry._api_format())

    @http.route(
        '/vn_care/api/v1/enquiries/<string:submission_id>/messages', type='http', auth='bearer',
        bearer_scope='vn_care', methods=['POST'], csrf=False, readonly=False)
    def post_customer_message(self, submission_id):
        """Add what the customer wrote in their website account to the enquiry.
        A message sent twice is stored once."""
        self._check_api_user()
        try:
            data = request.get_json_data()
        except ValueError:
            return self._error("The body must be valid JSON.", 400)
        # sudo - vn.care.enquiry: see create_enquiries
        enquiry = request.env['vn.care.enquiry'].sudo().search(
            [('submission_id', '=', submission_id)], limit=1)
        if not enquiry:
            return self._error("No enquiry for this submission.", 404)
        try:
            result = enquiry._api_post_customer_message(data)
        except (ValidationError, UserError) as error:
            return self._error(str(error), 422)
        return request.make_json_response(result, status=201 if result['created'] else 200)

    @http.route(
        '/vn_care/api/v1/categories', type='http', auth='bearer', bearer_scope='vn_care',
        methods=['GET'], readonly=True)
    def get_categories(self):
        self._check_api_user()
        # sudo - vn.care.category: see create_enquiries
        categories = request.env['vn.care.category'].sudo().search([])
        return request.make_json_response({
            'categories': [{'code': category.code, 'name': category.name} for category in categories],
        })

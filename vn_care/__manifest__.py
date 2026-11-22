{
    'name': 'Visit Nigeria Customer Care',
    'version': '1.0.0',
    'category': 'Services/Customer Care',
    'sequence': 10,
    'summary': 'Central dashboard for customer enquiries and service requests from VisitNigeria.io',
    'description': """
Customer Enquiries and Requests Management Dashboard
====================================================
Every enquiry submitted on VisitNigeria.io lands in one inbox where the
Customer Care team assigns, answers, tracks and closes it, without any access
to the website administration backend.
""",
    'author': 'Visit Nigeria',
    'website': 'https://visitnigeria.io',
    'depends': ['mail'],
    'data': [
        'security/vn_care_security.xml',
        'security/ir.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/ir_sequence_data.xml',
        'data/vn_care_category_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/vn_care_enquiry_views.xml',
        'views/vn_care_category_views.xml',
        'views/res_users_views.xml',
        'wizard/vn_care_user_invite_views.xml',
        'views/res_config_settings_views.xml',
        'views/vn_care_menus.xml',
    ],
    'demo': ['data/vn_care_demo.xml'],
    'assets': {
        'web.assets_backend': [
            'vn_care/static/src/**/*',
        ],
    },
    'application': True,
    'license': 'LGPL-3',
}

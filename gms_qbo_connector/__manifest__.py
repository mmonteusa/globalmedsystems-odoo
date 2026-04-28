{
    'name': 'GMS QuickBooks Online Connector',
    'version': '17.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Bidirectional sync between Odoo and QuickBooks Online',
    'description': """
        Full bidirectional sync between Odoo 17 and QuickBooks Online including:
        - Journal Entries (full double-entry sync)
        - Invoices and Bills
        - Payments
        - Customers and Vendors
        - Products and Categories
        - Chart of Accounts mapping
        - Tax mapping
        - Payment Terms
        Built for Global Med Systems / Global Med Auctions by Trinity Network Solutions.
    """,
    'author': 'Trinity Network Solutions',
    'website': 'https://www.trinitynetworksolutions.net',
    'depends': [
        'account',
        'sale',
        'purchase',
        'contacts',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/qbo_config_views.xml',
        'views/qbo_sync_views.xml',
        'views/qbo_log_views.xml',
        'views/qbo_menu.xml',
        'data/qbo_cron.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'external_dependencies': {
        'python': ['intuitlib', 'quickbooks'],
    },
}

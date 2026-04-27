{
    'name': 'Sign Employee Role Filter',
    'version': '17.0.1.0.0',
    'category': 'Sign',
    'summary': 'Restricts Sign Employee role signer search to internal users only',
    'description': """
        When assigning signers in the Odoo Sign send wizard,
        the Employee role field is restricted to only show
        internal users (res.users with share=False),
        preventing customer contacts from appearing in the
        Employee signer search results.
    """,
    'author': 'FiberFed / GMS Internal',
    'depends': ['sign'],
    'data': [],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

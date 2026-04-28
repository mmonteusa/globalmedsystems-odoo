import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class QboAccountMapping(models.Model):
    _name = 'qbo.account.mapping'
    _description = 'QBO Chart of Accounts Mapping'
    _rec_name = 'odoo_account_id'

    config_id = fields.Many2one('qbo.config', string='Connection',
                                 required=True, ondelete='cascade')
    odoo_account_id = fields.Many2one('account.account', string='Odoo Account',
                                       required=True)
    qbo_account_id = fields.Char(string='QBO Account ID', required=True)
    qbo_account_name = fields.Char(string='QBO Account Name')
    qbo_account_type = fields.Char(string='QBO Account Type')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_mapping', 'UNIQUE(config_id, odoo_account_id)',
         'Each Odoo account can only be mapped once per QBO connection.'),
    ]

    def action_fetch_qbo_accounts(self):
        """Fetch all accounts from QBO and display for mapping."""
        config = self.env['qbo.config'].search([
            ('company_id', '=', self.env.company.id),
            ('active', '=', True),
        ], limit=1)
        if not config:
            raise UserError(_('No active QBO connection found.'))

        result = config._query("SELECT * FROM Account WHERE Active = true MAXRESULTS 200")
        accounts = result.get('QueryResponse', {}).get('Account', [])

        # Return accounts as info for user to map
        account_list = '\n'.join([
            f"ID: {a['Id']} | {a['Name']} | {a.get('AccountType', '')} | {a.get('AccountSubType', '')}"
            for a in accounts
        ])
        _logger.info('QBO Accounts fetched:\n%s', account_list)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': f'Found {len(accounts)} QBO Accounts',
                'message': 'Check logs for full account list. Use IDs to create mappings.',
                'type': 'info',
                'sticky': True,
            }
        }


class QboTaxMapping(models.Model):
    _name = 'qbo.tax.mapping'
    _description = 'QBO Tax Mapping'
    _rec_name = 'odoo_tax_id'

    config_id = fields.Many2one('qbo.config', string='Connection',
                                 required=True, ondelete='cascade')
    odoo_tax_id = fields.Many2one('account.tax', string='Odoo Tax', required=True)
    qbo_tax_code_id = fields.Char(string='QBO Tax Code ID', required=True)
    qbo_tax_code_name = fields.Char(string='QBO Tax Code Name')
    qbo_tax_rate_id = fields.Char(string='QBO Tax Rate ID')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_tax_mapping', 'UNIQUE(config_id, odoo_tax_id)',
         'Each Odoo tax can only be mapped once per QBO connection.'),
    ]

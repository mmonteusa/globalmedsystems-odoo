from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class QboSyncWizard(models.TransientModel):
    _name = 'qbo.sync.wizard'
    _description = 'QBO Manual Sync Wizard'

    config_id = fields.Many2one('qbo.config', string='QBO Connection',
                                 required=True,
                                 default=lambda self: self.env['qbo.config'].search([
                                     ('active', '=', True),
                                     ('company_id', '=', self.env.company.id),
                                 ], limit=1))
    sync_what = fields.Selection([
        ('all', 'Full Sync — All Data'),
        ('customers', 'Customers Only'),
        ('vendors', 'Vendors Only'),
        ('products', 'Products Only'),
        ('invoices', 'Invoices Only'),
        ('bills', 'Bills Only'),
        ('journals', 'Journal Entries Only'),
        ('payments', 'Payments Only'),
    ], string='Sync What', required=True, default='all')
    direction = fields.Selection([
        ('bidirectional', 'Bidirectional'),
        ('odoo_to_qbo', 'Odoo → QBO'),
        ('qbo_to_odoo', 'QBO → Odoo'),
    ], string='Direction', required=True, default='bidirectional')
    result_summary = fields.Text(string='Result', readonly=True)

    def action_sync(self):
        """Execute the sync and show results."""
        self.ensure_one()
        if not self.config_id:
            raise UserError(_('Please select a QBO connection.'))

        config = self.config_id
        # Override direction for this run
        original_direction = config.sync_direction
        config.sync_direction = self.direction

        scheduler = self.env['qbo.scheduler']
        partner_sync = self.env['qbo.partner.sync']
        product_sync = self.env['qbo.product.sync']
        invoice_sync = self.env['qbo.invoice.sync']
        journal_sync = self.env['qbo.journal.sync']
        payment_sync = self.env['qbo.payment.sync']

        results = {}
        try:
            if self.sync_what == 'all':
                results = scheduler.run_full_sync(config)
            elif self.sync_what == 'customers':
                if self.direction in ('qbo_to_odoo', 'bidirectional'):
                    c, u = partner_sync.sync_customers_from_qbo(config)
                    results['from_qbo'] = f'{c} created, {u} updated'
                if self.direction in ('odoo_to_qbo', 'bidirectional'):
                    c, u = partner_sync.sync_customers_to_qbo(config)
                    results['to_qbo'] = f'{c} created, {u} updated'
            elif self.sync_what == 'vendors':
                c, u = partner_sync.sync_vendors_from_qbo(config)
                results['vendors'] = f'{c} created, {u} updated'
            elif self.sync_what == 'products':
                if self.direction in ('qbo_to_odoo', 'bidirectional'):
                    c, s = product_sync.sync_products_from_qbo(config)
                    results['from_qbo'] = f'{c} imported, {s} skipped'
                if self.direction in ('odoo_to_qbo', 'bidirectional'):
                    c, u, e = product_sync.sync_products_to_qbo(config)
                    results['to_qbo'] = f'{c} created, {u} updated, {e} errors'
            elif self.sync_what == 'invoices':
                if self.direction in ('qbo_to_odoo', 'bidirectional'):
                    c, s, e = invoice_sync.sync_invoices_from_qbo(config)
                    results['from_qbo'] = f'{c} imported, {s} skipped, {e} errors'
                if self.direction in ('odoo_to_qbo', 'bidirectional'):
                    c, u, e = invoice_sync.sync_invoices_to_qbo(config)
                    results['to_qbo'] = f'{c} created, {u} updated, {e} errors'
            elif self.sync_what == 'bills':
                c, e = invoice_sync.sync_bills_to_qbo(config)
                results['bills'] = f'{c} synced, {e} errors'
            elif self.sync_what == 'journals':
                if self.direction in ('qbo_to_odoo', 'bidirectional'):
                    c, s, e = journal_sync.sync_journal_entries_from_qbo(config)
                    results['from_qbo'] = f'{c} imported, {s} skipped, {e} errors'
                if self.direction in ('odoo_to_qbo', 'bidirectional'):
                    c, u, e = journal_sync.sync_journal_entries_to_qbo(config)
                    results['to_qbo'] = f'{c} created, {u} updated, {e} errors'
            elif self.sync_what == 'payments':
                c, e = payment_sync.sync_payments_to_qbo(config)
                results['payments'] = f'{c} synced, {e} errors'

        finally:
            # Restore original direction
            config.sync_direction = original_direction

        summary = '\n'.join([f'{k}: {v}' for k, v in results.items()])
        self.result_summary = summary or 'Sync complete — no records to process.'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'QBO Sync Complete',
                'message': self.result_summary,
                'type': 'success',
                'sticky': True,
            }
        }

import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class QboScheduler(models.Model):
    _name = 'qbo.scheduler'
    _description = 'QBO Sync Scheduler'

    @api.model
    def run_scheduled_sync(self):
        """Called by cron job — runs full sync for all active configs."""
        configs = self.env['qbo.config'].search([
            ('active', '=', True),
            ('auto_sync', '=', True),
        ])
        for config in configs:
            try:
                self.run_full_sync(config)
            except Exception as e:
                _logger.error('Scheduled QBO sync failed for %s: %s', config.name, e)
                config._log_error('scheduled_sync', str(e))

    def run_full_sync(self, config):
        """
        Run a full bidirectional sync based on config settings.
        This is the master orchestrator.
        """
        _logger.info('Starting full QBO sync for: %s', config.name)
        results = {}

        direction = config.sync_direction
        partner_sync = self.env['qbo.partner.sync']
        product_sync = self.env['qbo.product.sync']
        invoice_sync = self.env['qbo.invoice.sync']
        journal_sync = self.env['qbo.journal.sync']
        payment_sync = self.env['qbo.payment.sync']

        # ── Step 1: Partners (always sync from QBO first to get QBO IDs)
        if config.sync_customers:
            if direction in ('qbo_to_odoo', 'bidirectional'):
                c, u = partner_sync.sync_customers_from_qbo(config)
                results['customers_from_qbo'] = f'{c} created, {u} updated'
            if direction in ('odoo_to_qbo', 'bidirectional'):
                c, u = partner_sync.sync_customers_to_qbo(config)
                results['customers_to_qbo'] = f'{c} created, {u} updated'

        if config.sync_vendors:
            if direction in ('qbo_to_odoo', 'bidirectional'):
                c, u = partner_sync.sync_vendors_from_qbo(config)
                results['vendors_from_qbo'] = f'{c} created, {u} updated'

        # ── Step 2: Products
        if config.sync_products:
            if direction in ('qbo_to_odoo', 'bidirectional'):
                c, s = product_sync.sync_products_from_qbo(config)
                results['products_from_qbo'] = f'{c} imported, {s} skipped'
            if direction in ('odoo_to_qbo', 'bidirectional'):
                c, u, e = product_sync.sync_products_to_qbo(config)
                results['products_to_qbo'] = f'{c} created, {u} updated, {e} errors'

        # ── Step 3: Invoices
        if config.sync_invoices:
            if direction in ('qbo_to_odoo', 'bidirectional'):
                c, s, e = invoice_sync.sync_invoices_from_qbo(config)
                results['invoices_from_qbo'] = f'{c} imported, {s} skipped, {e} errors'
            if direction in ('odoo_to_qbo', 'bidirectional'):
                c, u, e = invoice_sync.sync_invoices_to_qbo(config)
                results['invoices_to_qbo'] = f'{c} created, {u} updated, {e} errors'

        # ── Step 4: Bills
        if config.sync_bills:
            if direction in ('odoo_to_qbo', 'bidirectional'):
                c, e = invoice_sync.sync_bills_to_qbo(config)
                results['bills_to_qbo'] = f'{c} synced, {e} errors'

        # ── Step 5: Journal Entries (KEY DIFFERENTIATOR)
        if config.sync_journal_entries:
            if direction in ('qbo_to_odoo', 'bidirectional'):
                c, s, e = journal_sync.sync_journal_entries_from_qbo(config)
                results['journals_from_qbo'] = f'{c} imported, {s} skipped, {e} errors'
            if direction in ('odoo_to_qbo', 'bidirectional'):
                c, u, e = journal_sync.sync_journal_entries_to_qbo(config)
                results['journals_to_qbo'] = f'{c} created, {u} updated, {e} errors'

        # ── Step 6: Payments
        if config.sync_payments:
            if direction in ('odoo_to_qbo', 'bidirectional'):
                c, e = payment_sync.sync_payments_to_qbo(config)
                results['payments_to_qbo'] = f'{c} synced, {e} errors'

        # Update last sync timestamp
        config.write({
            'last_sync': fields.Datetime.now(),
            'last_sync_status': 'success',
        })

        _logger.info('QBO sync complete for %s: %s', config.name, results)
        return results

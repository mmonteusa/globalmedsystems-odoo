import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class QboPaymentSync(models.Model):
    _name = 'qbo.payment.sync'
    _description = 'QBO Payment Sync Handler'

    def sync_payments_to_qbo(self, config):
        """Export Odoo payments to QBO."""
        payments = self.env['account.payment'].search([
            ('state', '=', 'posted'),
            ('qbo_synced', '=', False),
            ('company_id', '=', config.company_id.id),
        ])
        created = errors = 0

        for payment in payments:
            try:
                if not payment.partner_id or not payment.partner_id.qbo_id:
                    continue

                if payment.payment_type == 'inbound':
                    # Customer payment
                    data = {
                        'CustomerRef': {'value': payment.partner_id.qbo_id},
                        'TotalAmt': float(payment.amount),
                        'TxnDate': payment.date.strftime('%Y-%m-%d'),
                        'PrivateNote': f'Odoo payment: {payment.name}',
                    }
                    result = config._make_request('POST', 'payment',
                                                   data={'Payment': data})
                    new_id = result.get('Payment', {}).get('Id')
                else:
                    # Vendor payment (BillPayment)
                    data = {
                        'VendorRef': {'value': payment.partner_id.qbo_id},
                        'TotalAmt': float(payment.amount),
                        'TxnDate': payment.date.strftime('%Y-%m-%d'),
                        'PayType': 'Check',
                        'PrivateNote': f'Odoo payment: {payment.name}',
                    }
                    result = config._make_request('POST', 'billpayment',
                                                   data={'BillPayment': data})
                    new_id = result.get('BillPayment', {}).get('Id')

                if new_id:
                    payment.write({
                        'qbo_synced': True,
                        'qbo_sync_date': fields.Datetime.now(),
                    })
                created += 1

            except Exception as e:
                _logger.error('Error syncing payment %s: %s', payment.name, e)
                config._log_error(f'payment_{payment.id}', str(e))
                errors += 1

        config._log_success('sync_payments_to_qbo',
                             f'Payments: {created} synced, {errors} errors', created)
        return created, errors

    def sync_payments_from_qbo(self, config):
        """Import QBO payments into Odoo (read-only reference)."""
        result = config._query(
            "SELECT * FROM Payment MAXRESULTS 200"
        )
        payments = result.get('QueryResponse', {}).get('Payment', [])
        _logger.info('Found %d QBO payments to review', len(payments))
        config._log_success('sync_payments_from_qbo',
                             f'{len(payments)} QBO payments reviewed', len(payments))
        return len(payments)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    qbo_id = fields.Char(string='QBO ID', copy=False, index=True)
    qbo_synced = fields.Boolean(string='Synced to QBO', default=False)
    qbo_sync_date = fields.Datetime(string='Last QBO Sync', readonly=True)

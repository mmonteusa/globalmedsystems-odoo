import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class QboInvoiceSync(models.Model):
    _name = 'qbo.invoice.sync'
    _description = 'QBO Invoice and Bill Sync Handler'

    def _get_tax_qbo_id(self, tax, config):
        """Get QBO tax code ID for an Odoo tax."""
        mapping = self.env['qbo.tax.mapping'].search([
            ('config_id', '=', config.id),
            ('odoo_tax_id', '=', tax.id),
        ], limit=1)
        return mapping.qbo_tax_code_id if mapping else None

    def _invoice_to_qbo(self, invoice, config):
        """Convert Odoo customer invoice to QBO Invoice format."""
        if not invoice.partner_id.qbo_id:
            raise UserError(_(
                'Customer %s has no QBO ID. Please sync customers first.'
            ) % invoice.partner_id.name)

        lines = []
        for i, line in enumerate(invoice.invoice_line_ids):
            if not line.product_id:
                continue

            line_data = {
                'Id': str(i),
                'LineNum': i + 1,
                'Amount': float(line.price_subtotal),
                'DetailType': 'SalesItemLineDetail',
                'SalesItemLineDetail': {
                    'Qty': float(line.quantity),
                    'UnitPrice': float(line.price_unit),
                },
                'Description': line.name or '',
            }

            # Product reference
            if line.product_id.qbo_id:
                line_data['SalesItemLineDetail']['ItemRef'] = {
                    'value': line.product_id.qbo_id
                }

            # Tax
            if line.tax_ids:
                tax = line.tax_ids[0]
                qbo_tax_id = self._get_tax_qbo_id(tax, config)
                if qbo_tax_id:
                    line_data['SalesItemLineDetail']['TaxCodeRef'] = {
                        'value': qbo_tax_id
                    }

            lines.append(line_data)

        qbo_invoice = {
            'CustomerRef': {'value': invoice.partner_id.qbo_id},
            'TxnDate': invoice.invoice_date.strftime('%Y-%m-%d'),
            'DueDate': invoice.invoice_date_due.strftime('%Y-%m-%d') if invoice.invoice_date_due else None,
            'DocNumber': invoice.name,
            'Line': lines,
            'PrivateNote': f'Odoo ref: {invoice.name}',
        }

        # Remove None values
        qbo_invoice = {k: v for k, v in qbo_invoice.items() if v is not None}
        return qbo_invoice

    def _bill_to_qbo(self, bill, config):
        """Convert Odoo vendor bill to QBO Bill format."""
        if not bill.partner_id.qbo_id:
            raise UserError(_(
                'Vendor %s has no QBO ID. Please sync vendors first.'
            ) % bill.partner_id.name)

        lines = []
        for i, line in enumerate(bill.invoice_line_ids):
            qbo_account_id = None
            if line.account_id:
                mapping = self.env['qbo.account.mapping'].search([
                    ('config_id', '=', config.id),
                    ('odoo_account_id', '=', line.account_id.id),
                ], limit=1)
                if mapping:
                    qbo_account_id = mapping.qbo_account_id

            line_data = {
                'Id': str(i),
                'LineNum': i + 1,
                'Amount': float(line.price_subtotal),
                'DetailType': 'AccountBasedExpenseLineDetail',
                'AccountBasedExpenseLineDetail': {
                    'AccountRef': {'value': qbo_account_id or ''},
                },
                'Description': line.name or '',
            }
            lines.append(line_data)

        return {
            'VendorRef': {'value': bill.partner_id.qbo_id},
            'TxnDate': bill.invoice_date.strftime('%Y-%m-%d'),
            'DueDate': bill.invoice_date_due.strftime('%Y-%m-%d') if bill.invoice_date_due else None,
            'DocNumber': bill.name,
            'Line': lines,
            'PrivateNote': f'Odoo ref: {bill.name}',
        }

    def sync_invoices_to_qbo(self, config):
        """Export posted customer invoices to QBO."""
        invoices = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('qbo_synced', '=', False),
            ('company_id', '=', config.company_id.id),
        ])

        created = updated = errors = 0

        for invoice in invoices:
            try:
                data = self._invoice_to_qbo(invoice, config)

                if invoice.qbo_id:
                    existing = config._make_request('GET', f'invoice/{invoice.qbo_id}')
                    qbo_inv = existing.get('Invoice', {})
                    data['Id'] = invoice.qbo_id
                    data['SyncToken'] = qbo_inv.get('SyncToken', '0')
                    config._make_request('POST', 'invoice',
                                          data={'Invoice': data, 'sparse': True})
                    updated += 1
                else:
                    result = config._make_request('POST', 'invoice',
                                                   data={'Invoice': data})
                    new_id = result.get('Invoice', {}).get('Id')
                    if new_id:
                        invoice.write({
                            'qbo_id': str(new_id),
                            'qbo_synced': True,
                            'qbo_sync_date': fields.Datetime.now(),
                        })
                    created += 1

            except Exception as e:
                _logger.error('Error syncing invoice %s: %s', invoice.name, e)
                config._log_error(f'invoice_{invoice.id}', str(e))
                errors += 1

        config._log_success(
            'sync_invoices_to_qbo',
            f'Invoices: {created} created, {updated} updated, {errors} errors',
            created + updated
        )
        return created, updated, errors

    def sync_invoices_from_qbo(self, config):
        """Import QBO invoices into Odoo."""
        result = config._query(
            "SELECT * FROM Invoice WHERE TxnDate > '2020-01-01' MAXRESULTS 500"
        )
        invoices = result.get('QueryResponse', {}).get('Invoice', [])
        created = skipped = errors = 0

        for qbo_inv in invoices:
            qbo_id = str(qbo_inv.get('Id', ''))
            existing = self.env['account.move'].search([
                ('qbo_id', '=', qbo_id)
            ], limit=1)
            if existing:
                skipped += 1
                continue

            try:
                customer_ref = qbo_inv.get('CustomerRef', {})
                customer_qbo_id = customer_ref.get('value')
                partner = self.env['res.partner'].search([
                    ('qbo_id', '=', customer_qbo_id)
                ], limit=1)

                if not partner:
                    _logger.warning('Customer not found for QBO ID: %s', customer_qbo_id)
                    errors += 1
                    continue

                journal = self.env['account.journal'].search([
                    ('type', '=', 'sale'),
                    ('company_id', '=', config.company_id.id),
                ], limit=1)

                move_vals = {
                    'move_type': 'out_invoice',
                    'partner_id': partner.id,
                    'journal_id': journal.id,
                    'invoice_date': qbo_inv.get('TxnDate'),
                    'invoice_date_due': qbo_inv.get('DueDate'),
                    'ref': qbo_inv.get('DocNumber', ''),
                    'qbo_id': qbo_id,
                    'qbo_synced': True,
                    'qbo_sync_date': fields.Datetime.now(),
                    'invoice_line_ids': [],
                }

                for line in qbo_inv.get('Line', []):
                    if line.get('DetailType') != 'SalesItemLineDetail':
                        continue
                    detail = line.get('SalesItemLineDetail', {})
                    move_vals['invoice_line_ids'].append((0, 0, {
                        'name': line.get('Description', 'QBO Import'),
                        'quantity': float(detail.get('Qty', 1)),
                        'price_unit': float(detail.get('UnitPrice', 0)),
                    }))

                if move_vals['invoice_line_ids']:
                    self.env['account.move'].create(move_vals)
                    created += 1

            except Exception as e:
                _logger.error('Error importing QBO invoice %s: %s', qbo_id, e)
                config._log_error(f'import_invoice_{qbo_id}', str(e))
                errors += 1

        config._log_success(
            'sync_invoices_from_qbo',
            f'Invoices: {created} imported, {skipped} skipped, {errors} errors',
            created
        )
        return created, skipped, errors

    def sync_bills_to_qbo(self, config):
        """Export vendor bills to QBO."""
        bills = self.env['account.move'].search([
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
            ('qbo_synced', '=', False),
            ('company_id', '=', config.company_id.id),
        ])
        created = errors = 0
        for bill in bills:
            try:
                data = self._bill_to_qbo(bill, config)
                result = config._make_request('POST', 'bill', data={'Bill': data})
                new_id = result.get('Bill', {}).get('Id')
                if new_id:
                    bill.write({
                        'qbo_id': str(new_id),
                        'qbo_synced': True,
                        'qbo_sync_date': fields.Datetime.now(),
                    })
                created += 1
            except Exception as e:
                _logger.error('Error syncing bill %s: %s', bill.name, e)
                config._log_error(f'bill_{bill.id}', str(e))
                errors += 1

        config._log_success('sync_bills_to_qbo',
                             f'Bills: {created} synced, {errors} errors', created)
        return created, errors

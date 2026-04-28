import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    qbo_id = fields.Char(string='QBO ID', copy=False, index=True)
    qbo_sync_date = fields.Datetime(string='Last QBO Sync', readonly=True)
    qbo_synced = fields.Boolean(string='Synced to QBO', default=False)
    qbo_doc_number = fields.Char(string='QBO Doc Number', readonly=True)


class QboJournalSync(models.Model):
    _name = 'qbo.journal.sync'
    _description = 'QBO Journal Entry Sync Handler'

    def _get_account_qbo_id(self, account, config):
        """Get QBO account ID for an Odoo account via mapping."""
        mapping = self.env['qbo.account.mapping'].search([
            ('config_id', '=', config.id),
            ('odoo_account_id', '=', account.id),
        ], limit=1)
        if not mapping:
            raise UserError(_(
                'No QBO mapping found for account: %s (%s). '
                'Please configure account mappings first.'
            ) % (account.name, account.code))
        return mapping.qbo_account_id

    def _journal_entry_to_qbo(self, move, config):
        """
        Convert an Odoo journal entry to QBO JournalEntry format.
        This is the core differentiator — full double-entry sync.
        """
        lines = []
        for i, line in enumerate(move.line_ids):
            if line.debit == 0 and line.credit == 0:
                continue

            qbo_account_id = self._get_account_qbo_id(line.account_id, config)

            detail = {
                'PostingType': 'Debit' if line.debit > 0 else 'Credit',
                'Amount': float(line.debit if line.debit > 0 else line.credit),
                'AccountRef': {'value': qbo_account_id},
            }

            # Add partner/entity if applicable
            if line.partner_id and line.partner_id.qbo_id:
                detail['Entity'] = {
                    'EntityRef': {'value': line.partner_id.qbo_id},
                    'Type': 'Customer' if line.partner_id.customer_rank > 0 else 'Vendor',
                }

            # Add description
            if line.name:
                detail['Description'] = line.name[:4000]

            lines.append({
                'Id': str(i),
                'JournalEntryLineDetail': detail,
                'DetailType': 'JournalEntryLineDetail',
                'Amount': float(line.debit if line.debit > 0 else line.credit),
                'Description': line.name or '',
            })

        qbo_entry = {
            'DocNumber': move.name,
            'TxnDate': move.date.strftime('%Y-%m-%d'),
            'Line': lines,
            'PrivateNote': f'Synced from Odoo: {move.name} | Ref: {move.ref or ""}',
        }

        return qbo_entry

    def _qbo_to_journal_entry(self, qbo_entry, config):
        """Convert QBO JournalEntry to Odoo journal entry."""
        journal = self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', config.company_id.id),
        ], limit=1)

        if not journal:
            raise UserError(_('No general journal found. Please create one.'))

        line_ids = []
        for line in qbo_entry.get('Line', []):
            detail = line.get('JournalEntryLineDetail', {})
            account_ref = detail.get('AccountRef', {})
            qbo_account_id = account_ref.get('value')

            # Find mapped Odoo account
            mapping = self.env['qbo.account.mapping'].search([
                ('config_id', '=', config.id),
                ('qbo_account_id', '=', qbo_account_id),
            ], limit=1)

            if not mapping:
                _logger.warning('No Odoo mapping for QBO account ID: %s', qbo_account_id)
                continue

            amount = float(line.get('Amount', 0))
            posting_type = detail.get('PostingType', 'Debit')

            line_vals = {
                'account_id': mapping.odoo_account_id.id,
                'name': line.get('Description', ''),
                'debit': amount if posting_type == 'Debit' else 0,
                'credit': amount if posting_type == 'Credit' else 0,
            }

            # Partner matching
            entity = detail.get('Entity', {})
            if entity:
                entity_ref = entity.get('EntityRef', {})
                entity_id = entity_ref.get('value')
                if entity_id:
                    partner = self.env['res.partner'].search([
                        ('qbo_id', '=', entity_id)
                    ], limit=1)
                    if partner:
                        line_vals['partner_id'] = partner.id

            line_ids.append((0, 0, line_vals))

        if not line_ids:
            return None

        txn_date = qbo_entry.get('TxnDate', fields.Date.today())
        move_vals = {
            'journal_id': journal.id,
            'date': txn_date,
            'ref': qbo_entry.get('DocNumber', ''),
            'narration': qbo_entry.get('PrivateNote', ''),
            'qbo_id': str(qbo_entry.get('Id', '')),
            'qbo_synced': True,
            'qbo_sync_date': fields.Datetime.now(),
            'qbo_doc_number': qbo_entry.get('DocNumber', ''),
            'line_ids': line_ids,
        }
        return move_vals

    def sync_journal_entries_to_qbo(self, config):
        """Export Odoo journal entries to QBO."""
        # Get unsynced posted journal entries (not invoices/bills)
        moves = self.env['account.move'].search([
            ('move_type', '=', 'entry'),
            ('state', '=', 'posted'),
            ('qbo_synced', '=', False),
            ('company_id', '=', config.company_id.id),
        ])

        created = updated = errors = 0

        for move in moves:
            try:
                qbo_data = self._journal_entry_to_qbo(move, config)

                if move.qbo_id:
                    # Update existing
                    existing = config._make_request(
                        'GET', f'journalentry/{move.qbo_id}'
                    )
                    qbo_entry = existing.get('JournalEntry', {})
                    qbo_data['Id'] = move.qbo_id
                    qbo_data['SyncToken'] = qbo_entry.get('SyncToken', '0')
                    config._make_request('POST', 'journalentry',
                                          data={'JournalEntry': qbo_data, 'sparse': True})
                    updated += 1
                else:
                    result = config._make_request('POST', 'journalentry',
                                                   data={'JournalEntry': qbo_data})
                    new_id = result.get('JournalEntry', {}).get('Id')
                    if new_id:
                        move.write({
                            'qbo_id': str(new_id),
                            'qbo_synced': True,
                            'qbo_sync_date': fields.Datetime.now(),
                        })
                    created += 1

            except Exception as e:
                _logger.error('Error syncing journal entry %s: %s', move.name, e)
                config._log_error(f'journal_entry_{move.id}', str(e))
                errors += 1

        config._log_success(
            'sync_journal_entries_to_qbo',
            f'Journal entries: {created} created, {updated} updated, {errors} errors',
            created + updated
        )
        return created, updated, errors

    def sync_journal_entries_from_qbo(self, config):
        """Import QBO journal entries into Odoo."""
        result = config._query(
            "SELECT * FROM JournalEntry MAXRESULTS 500"
        )
        entries = result.get('QueryResponse', {}).get('JournalEntry', [])
        created = skipped = errors = 0

        for qbo_entry in entries:
            qbo_id = str(qbo_entry.get('Id', ''))

            # Skip if already imported
            existing = self.env['account.move'].search([
                ('qbo_id', '=', qbo_id)
            ], limit=1)
            if existing:
                skipped += 1
                continue

            try:
                move_vals = self._qbo_to_journal_entry(qbo_entry, config)
                if move_vals:
                    move = self.env['account.move'].create(move_vals)
                    move.action_post()
                    created += 1
            except Exception as e:
                _logger.error('Error importing QBO journal entry %s: %s', qbo_id, e)
                config._log_error(f'import_journal_{qbo_id}', str(e))
                errors += 1

        config._log_success(
            'sync_journal_entries_from_qbo',
            f'Journal entries: {created} imported, {skipped} skipped, {errors} errors',
            created
        )
        return created, skipped, errors

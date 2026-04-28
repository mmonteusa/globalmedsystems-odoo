import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class QboSyncLog(models.Model):
    _name = 'qbo.sync.log'
    _description = 'QBO Sync Log'
    _order = 'create_date desc'
    _rec_name = 'operation'

    config_id = fields.Many2one('qbo.config', string='Connection', ondelete='cascade')
    operation = fields.Char(string='Operation', required=True)
    status = fields.Selection([
        ('success', 'Success'),
        ('partial', 'Partial'),
        ('error', 'Error'),
        ('info', 'Info'),
    ], string='Status', required=True, default='info')
    message = fields.Text(string='Message')
    detail = fields.Text(string='Detail / Raw Response')
    records_synced = fields.Integer(string='Records Synced', default=0)
    odoo_record = fields.Char(string='Odoo Record')
    qbo_id = fields.Char(string='QBO ID')
    create_date = fields.Datetime(string='Timestamp', readonly=True)

    def action_clear_logs(self):
        """Clear all logs older than 30 days."""
        cutoff = fields.Datetime.now()
        old_logs = self.search([
            ('create_date', '<', cutoff),
            ('status', '=', 'success'),
        ])
        old_logs.unlink()
        return True

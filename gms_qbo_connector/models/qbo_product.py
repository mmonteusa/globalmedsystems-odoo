import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    qbo_id = fields.Char(string='QBO Item ID', copy=False, index=True)
    qbo_synced = fields.Boolean(string='Synced to QBO', default=False)
    qbo_sync_date = fields.Datetime(string='Last QBO Sync', readonly=True)


class QboProductSync(models.Model):
    _name = 'qbo.product.sync'
    _description = 'QBO Product Sync Handler'

    def _product_to_qbo(self, product, config):
        """Convert Odoo product to QBO Item format."""
        data = {
            'Name': product.name[:100],
            'Active': product.active,
            'Type': 'Service' if product.type == 'service' else 'NonInventory',
            'Description': product.description_sale or '',
            'UnitPrice': float(product.list_price),
            'PurchaseCost': float(product.standard_price),
        }

        # Income account
        if product.property_account_income_id:
            mapping = self.env['qbo.account.mapping'].search([
                ('config_id', '=', config.id),
                ('odoo_account_id', '=', product.property_account_income_id.id),
            ], limit=1)
            if mapping:
                data['IncomeAccountRef'] = {'value': mapping.qbo_account_id}

        # Expense account
        if product.property_account_expense_id:
            mapping = self.env['qbo.account.mapping'].search([
                ('config_id', '=', config.id),
                ('odoo_account_id', '=', product.property_account_expense_id.id),
            ], limit=1)
            if mapping:
                data['ExpenseAccountRef'] = {'value': mapping.qbo_account_id}

        return data

    def sync_products_to_qbo(self, config):
        """Export Odoo products to QBO."""
        products = self.env['product.template'].search([
            ('qbo_synced', '=', False),
            ('active', '=', True),
        ])
        created = updated = errors = 0

        for product in products:
            try:
                data = self._product_to_qbo(product, config)
                if product.qbo_id:
                    existing = config._make_request('GET', f'item/{product.qbo_id}')
                    qbo_item = existing.get('Item', {})
                    data['Id'] = product.qbo_id
                    data['SyncToken'] = qbo_item.get('SyncToken', '0')
                    config._make_request('POST', 'item',
                                          data={'Item': data, 'sparse': True})
                    updated += 1
                else:
                    result = config._make_request('POST', 'item', data={'Item': data})
                    new_id = result.get('Item', {}).get('Id')
                    if new_id:
                        product.write({
                            'qbo_id': str(new_id),
                            'qbo_synced': True,
                            'qbo_sync_date': fields.Datetime.now(),
                        })
                    created += 1
            except Exception as e:
                _logger.error('Error syncing product %s: %s', product.name, e)
                config._log_error(f'product_{product.id}', str(e))
                errors += 1

        config._log_success('sync_products_to_qbo',
                             f'Products: {created} created, {updated} updated, {errors} errors',
                             created + updated)
        return created, updated, errors

    def sync_products_from_qbo(self, config):
        """Import QBO items into Odoo products."""
        result = config._query(
            "SELECT * FROM Item WHERE Active = true MAXRESULTS 500"
        )
        items = result.get('QueryResponse', {}).get('Item', [])
        created = skipped = 0

        for item in items:
            qbo_id = str(item.get('Id', ''))
            existing = self.env['product.template'].search([
                ('qbo_id', '=', qbo_id)
            ], limit=1)
            if existing:
                skipped += 1
                continue

            self.env['product.template'].create({
                'name': item.get('Name', ''),
                'list_price': float(item.get('UnitPrice', 0)),
                'standard_price': float(item.get('PurchaseCost', 0)),
                'type': 'service' if item.get('Type') == 'Service' else 'consu',
                'description_sale': item.get('Description', ''),
                'qbo_id': qbo_id,
                'qbo_synced': True,
                'qbo_sync_date': fields.Datetime.now(),
            })
            created += 1

        config._log_success('sync_products_from_qbo',
                             f'Products: {created} imported, {skipped} skipped',
                             created)
        return created, skipped

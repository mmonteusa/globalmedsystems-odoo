import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    qbo_id = fields.Char(string='QBO ID', copy=False, index=True)
    qbo_sync_date = fields.Datetime(string='Last QBO Sync', readonly=True)
    qbo_synced = fields.Boolean(string='Synced to QBO', default=False)


class QboPartnerSync(models.Model):
    _name = 'qbo.partner.sync'
    _description = 'QBO Partner Sync Handler'

    def _partner_to_qbo(self, partner, config):
        """Convert Odoo partner to QBO Customer/Vendor format."""
        data = {
            'DisplayName': partner.name,
            'Active': partner.active,
        }
        if partner.email:
            data['PrimaryEmailAddr'] = {'Address': partner.email}
        if partner.phone:
            data['PrimaryPhone'] = {'FreeFormNumber': partner.phone}
        if partner.street:
            data['BillAddr'] = {
                'Line1': partner.street or '',
                'Line2': partner.street2 or '',
                'City': partner.city or '',
                'CountrySubDivisionCode': partner.state_id.code if partner.state_id else '',
                'PostalCode': partner.zip or '',
                'Country': partner.country_id.code if partner.country_id else 'US',
            }
        if partner.website:
            data['WebAddr'] = {'URI': partner.website}
        if partner.ref:
            data['AcctNum'] = partner.ref
        return data

    def _qbo_to_partner(self, qbo_customer):
        """Convert QBO Customer to Odoo partner format."""
        vals = {
            'name': qbo_customer.get('DisplayName', ''),
            'qbo_id': str(qbo_customer.get('Id', '')),
            'qbo_synced': True,
            'qbo_sync_date': fields.Datetime.now(),
            'active': qbo_customer.get('Active', True),
        }
        # Email
        email_data = qbo_customer.get('PrimaryEmailAddr', {})
        if email_data:
            vals['email'] = email_data.get('Address', '')
        # Phone
        phone_data = qbo_customer.get('PrimaryPhone', {})
        if phone_data:
            vals['phone'] = phone_data.get('FreeFormNumber', '')
        # Address
        addr = qbo_customer.get('BillAddr', {})
        if addr:
            vals['street'] = addr.get('Line1', '')
            vals['street2'] = addr.get('Line2', '')
            vals['city'] = addr.get('City', '')
            vals['zip'] = addr.get('PostalCode', '')
            # State
            state_code = addr.get('CountrySubDivisionCode', '')
            if state_code:
                state = self.env['res.country.state'].search([
                    ('code', '=', state_code),
                    ('country_id.code', '=', 'US'),
                ], limit=1)
                if state:
                    vals['state_id'] = state.id
            # Country
            country_code = addr.get('Country', 'US')
            country = self.env['res.country'].search([
                ('code', '=', country_code)
            ], limit=1)
            if country:
                vals['country_id'] = country.id
        return vals

    def sync_customers_from_qbo(self, config):
        """Import all customers from QBO into Odoo."""
        _logger.info('Starting customer sync from QBO...')
        result = config._query(
            "SELECT * FROM Customer WHERE Active = true MAXRESULTS 1000"
        )
        customers = result.get('QueryResponse', {}).get('Customer', [])
        created = updated = 0

        for qbo_customer in customers:
            qbo_id = str(qbo_customer.get('Id', ''))
            vals = self._qbo_to_partner(qbo_customer)
            vals['customer_rank'] = 1

            # Check if partner already exists by QBO ID
            existing = self.env['res.partner'].search([
                ('qbo_id', '=', qbo_id)
            ], limit=1)

            if existing:
                existing.write(vals)
                updated += 1
            else:
                # Try matching by email to avoid duplicates
                if vals.get('email'):
                    by_email = self.env['res.partner'].search([
                        ('email', '=', vals['email']),
                        ('qbo_id', '=', False),
                    ], limit=1)
                    if by_email:
                        by_email.write(vals)
                        updated += 1
                        continue
                self.env['res.partner'].create(vals)
                created += 1

        config._log_success(
            'sync_customers_from_qbo',
            f'Customers synced: {created} created, {updated} updated',
            created + updated
        )
        _logger.info('Customer sync complete: %d created, %d updated', created, updated)
        return created, updated

    def sync_customers_to_qbo(self, config):
        """Export Odoo customers to QBO."""
        partners = self.env['res.partner'].search([
            ('customer_rank', '>', 0),
            ('qbo_synced', '=', False),
            ('active', '=', True),
        ])
        created = updated = 0

        for partner in partners:
            data = self._partner_to_qbo(partner, config)
            try:
                if partner.qbo_id:
                    # Update existing
                    existing = config._make_request(
                        'GET', f'customer/{partner.qbo_id}'
                    )
                    qbo_customer = existing.get('Customer', {})
                    data['Id'] = partner.qbo_id
                    data['SyncToken'] = qbo_customer.get('SyncToken', '0')
                    config._make_request('POST', 'customer', data={'Customer': data,
                                                                    'sparse': True})
                    updated += 1
                else:
                    # Create new
                    result = config._make_request('POST', 'customer',
                                                   data={'Customer': data})
                    new_id = result.get('Customer', {}).get('Id')
                    if new_id:
                        partner.write({
                            'qbo_id': str(new_id),
                            'qbo_synced': True,
                            'qbo_sync_date': fields.Datetime.now(),
                        })
                    created += 1
            except Exception as e:
                _logger.error('Error syncing partner %s to QBO: %s', partner.name, e)
                config._log_error(f'sync_customer_{partner.id}', str(e))

        config._log_success(
            'sync_customers_to_qbo',
            f'Customers exported: {created} created, {updated} updated',
            created + updated
        )
        return created, updated

    def sync_vendors_from_qbo(self, config):
        """Import all vendors from QBO into Odoo."""
        result = config._query(
            "SELECT * FROM Vendor WHERE Active = true MAXRESULTS 1000"
        )
        vendors = result.get('QueryResponse', {}).get('Vendor', [])
        created = updated = 0

        for qbo_vendor in vendors:
            qbo_id = str(qbo_vendor.get('Id', ''))
            vals = self._qbo_to_partner(qbo_vendor)
            vals['supplier_rank'] = 1

            existing = self.env['res.partner'].search([
                ('qbo_id', '=', qbo_id)
            ], limit=1)

            if existing:
                existing.write(vals)
                updated += 1
            else:
                self.env['res.partner'].create(vals)
                created += 1

        config._log_success(
            'sync_vendors_from_qbo',
            f'Vendors synced: {created} created, {updated} updated',
            created + updated
        )
        return created, updated

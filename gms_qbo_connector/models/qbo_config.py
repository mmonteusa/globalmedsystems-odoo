import logging
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

QBO_AUTHORIZATION_URL = 'https://appcenter.intuit.com/connect/oauth2'
QBO_TOKEN_URL = 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer'
QBO_REVOKE_URL = 'https://developer.api.intuit.com/v2/oauth2/tokens/revoke'
QBO_BASE_URL_PRODUCTION = 'https://quickbooks.api.intuit.com'
QBO_BASE_URL_SANDBOX = 'https://sandbox-quickbooks.api.intuit.com'
QBO_SCOPES = 'com.intuit.quickbooks.accounting'


class QboConfig(models.Model):
    _name = 'qbo.config'
    _description = 'QuickBooks Online Configuration'
    _rec_name = 'name'

    name = fields.Char(string='Instance Name', required=True, default='GMS QBO Connection')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
                                  default=lambda self: self.env.company, required=True)

    # ── OAuth Credentials ────────────────────────────────────────
    client_id = fields.Char(string='Client ID', required=True)
    client_secret = fields.Char(string='Client Secret', required=True)
    realm_id = fields.Char(string='Realm ID (Company ID)', required=True)
    redirect_uri = fields.Char(string='Redirect URI', required=True,
                                default='https://globalmedsystems.odoo.com/web/callback')
    environment = fields.Selection([
        ('sandbox', 'Sandbox (Testing)'),
        ('production', 'Production'),
    ], string='Environment', default='sandbox', required=True)

    # ── Token Storage ────────────────────────────────────────────
    access_token = fields.Text(string='Access Token', readonly=True)
    refresh_token = fields.Text(string='Refresh Token', readonly=True)
    token_expiry = fields.Datetime(string='Token Expires At', readonly=True)
    is_connected = fields.Boolean(string='Connected', compute='_compute_is_connected', store=False)
    connection_status = fields.Char(string='Status', compute='_compute_is_connected')

    # ── Sync Settings ────────────────────────────────────────────
    sync_invoices = fields.Boolean(string='Sync Invoices', default=True)
    sync_bills = fields.Boolean(string='Sync Bills', default=True)
    sync_payments = fields.Boolean(string='Sync Payments', default=True)
    sync_journal_entries = fields.Boolean(string='Sync Journal Entries', default=True)
    sync_customers = fields.Boolean(string='Sync Customers', default=True)
    sync_vendors = fields.Boolean(string='Sync Vendors', default=True)
    sync_products = fields.Boolean(string='Sync Products', default=True)
    sync_direction = fields.Selection([
        ('odoo_to_qbo', 'Odoo → QBO Only'),
        ('qbo_to_odoo', 'QBO → Odoo Only'),
        ('bidirectional', 'Bidirectional'),
    ], string='Sync Direction', default='bidirectional', required=True)

    # ── Auto Sync ────────────────────────────────────────────────
    auto_sync = fields.Boolean(string='Auto Sync', default=False)
    sync_interval = fields.Integer(string='Sync Every (Hours)', default=6)
    last_sync = fields.Datetime(string='Last Sync', readonly=True)
    last_sync_status = fields.Selection([
        ('success', 'Success'),
        ('partial', 'Partial'),
        ('error', 'Error'),
    ], string='Last Sync Status', readonly=True)

    @api.depends('access_token', 'token_expiry')
    def _compute_is_connected(self):
        for rec in self:
            if rec.access_token and rec.token_expiry:
                if rec.token_expiry > fields.Datetime.now():
                    rec.is_connected = True
                    rec.connection_status = '✅ Connected'
                else:
                    rec.is_connected = False
                    rec.connection_status = '⚠️ Token Expired — Refresh Needed'
            else:
                rec.is_connected = False
                rec.connection_status = '🔴 Not Connected'

    def _get_base_url(self):
        self.ensure_one()
        if self.environment == 'production':
            return QBO_BASE_URL_PRODUCTION
        return QBO_BASE_URL_SANDBOX

    def action_authorize(self):
        """Generate OAuth2 authorization URL and redirect user to Intuit."""
        self.ensure_one()
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'scope': QBO_SCOPES,
            'redirect_uri': self.redirect_uri,
            'state': f'qbo_config_{self.id}',
        }
        auth_url = f"{QBO_AUTHORIZATION_URL}?{urlencode(params)}"
        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def action_exchange_code(self, code):
        """Exchange authorization code for access + refresh tokens."""
        self.ensure_one()
        response = requests.post(QBO_TOKEN_URL, data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.redirect_uri,
        }, auth=(self.client_id, self.client_secret))

        if response.status_code != 200:
            raise UserError(_(
                'Failed to exchange authorization code: %s' % response.text
            ))

        token_data = response.json()
        self._store_tokens(token_data)
        return True

    def action_refresh_token(self):
        """Refresh the access token using the refresh token."""
        self.ensure_one()
        if not self.refresh_token:
            raise UserError(_('No refresh token available. Please re-authorize.'))

        response = requests.post(QBO_TOKEN_URL, data={
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
        }, auth=(self.client_id, self.client_secret))

        if response.status_code != 200:
            raise UserError(_(
                'Failed to refresh token: %s — Please re-authorize.' % response.text
            ))

        token_data = response.json()
        self._store_tokens(token_data)
        _logger.info('QBO token refreshed successfully for %s', self.name)
        return True

    def _store_tokens(self, token_data):
        """Store OAuth tokens securely."""
        expiry = fields.Datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600))
        self.write({
            'access_token': token_data['access_token'],
            'refresh_token': token_data.get('refresh_token', self.refresh_token),
            'token_expiry': expiry,
        })

    def _ensure_valid_token(self):
        """Ensure token is valid, refresh if needed."""
        self.ensure_one()
        if not self.access_token:
            raise UserError(_('Not connected to QuickBooks. Please authorize first.'))

        # Refresh if expiring within 5 minutes
        if self.token_expiry and self.token_expiry < fields.Datetime.now() + timedelta(minutes=5):
            self.action_refresh_token()

    def _make_request(self, method, endpoint, data=None, params=None):
        """Make an authenticated API request to QBO."""
        self.ensure_one()
        self._ensure_valid_token()

        base_url = self._get_base_url()
        url = f"{base_url}/v3/company/{self.realm_id}/{endpoint}"

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }

        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=data,
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            _logger.error('QBO API error: %s — %s', e, response.text)
            self._log_error(endpoint, str(e), response.text)
            raise UserError(_('QBO API Error: %s' % response.text))
        except requests.exceptions.RequestException as e:
            _logger.error('QBO connection error: %s', e)
            raise UserError(_('Connection error: %s' % str(e)))

    def _query(self, sql_query):
        """Execute a QBO SQL query."""
        return self._make_request('GET', 'query', params={'query': sql_query})

    def _log_error(self, operation, error_msg, detail=None):
        """Log an error to the sync log."""
        self.env['qbo.sync.log'].create({
            'config_id': self.id,
            'operation': operation,
            'status': 'error',
            'message': error_msg,
            'detail': detail or '',
        })

    def _log_success(self, operation, message, records_count=0):
        """Log a successful sync operation."""
        self.env['qbo.sync.log'].create({
            'config_id': self.id,
            'operation': operation,
            'status': 'success',
            'message': message,
            'records_synced': records_count,
        })

    def action_test_connection(self):
        """Test the QBO connection by fetching company info."""
        self.ensure_one()
        try:
            result = self._make_request('GET', 'companyinfo/' + self.realm_id)
            company_name = result.get('CompanyInfo', {}).get('CompanyName', 'Unknown')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Successful',
                    'message': f'Connected to QBO company: {company_name}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Failed',
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_disconnect(self):
        """Revoke tokens and disconnect."""
        self.ensure_one()
        if self.refresh_token:
            try:
                requests.post(QBO_REVOKE_URL,
                              data={'token': self.refresh_token},
                              auth=(self.client_id, self.client_secret))
            except Exception:
                pass
        self.write({
            'access_token': False,
            'refresh_token': False,
            'token_expiry': False,
        })

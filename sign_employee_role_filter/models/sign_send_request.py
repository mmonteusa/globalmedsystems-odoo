from odoo import models, api, fields

EMPLOYEE_ROLE_ID = 3
CUSTOMER_ROLE_ID = 1

class SignSendRequestSigner(models.Model):
    _inherit = 'sign.send.request.signer'

    @api.onchange('role_id', 'partner_id')
    def _onchange_role_id(self):
        res = {}
        if self.role_id and self.role_id.id == EMPLOYEE_ROLE_ID:
            res['domain'] = {'partner_id': [
                ('user_ids', '!=', False),
                ('user_ids.share', '=', False),
                ('user_ids.active', '=', True),
            ]}
            self.mail_sent_order = 1
        elif self.role_id and self.role_id.id == CUSTOMER_ROLE_ID:
            res['domain'] = {'partner_id': []}
            self.mail_sent_order = 2
        else:
            res['domain'] = {'partner_id': []}
        return res

class SignSendRequest(models.TransientModel):
    _inherit = 'sign.send.request'

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'set_sign_order' in fields_list:
            res['set_sign_order'] = True
        return res

    def _get_employee_partner_domain(self):
        return [
            ('user_ids', '!=', False),
            ('user_ids.share', '=', False),
            ('user_ids.active', '=', True),
        ]

from odoo import models, api


# ID of the Employee role in sign.item.role
# Verified: ID 3 = Employee on this instance
EMPLOYEE_ROLE_ID = 3


class SignSendRequestSigner(models.Model):
    _inherit = 'sign.send.request.signer'

    @api.onchange('role_id', 'partner_id')
    def _onchange_role_id(self):
        """
        When the role is set to Employee, restrict the partner
        domain to internal users only (res.partner records that
        have at least one linked internal user account).

        For all other roles (Customer, Company, Standard, etc.)
        the full res.partner domain is returned as normal.
        """
        res = {}
        if self.role_id and self.role_id.id == EMPLOYEE_ROLE_ID:
            res['domain'] = {
                'partner_id': [
                    ('user_ids', '!=', False),
                    ('user_ids.share', '=', False),
                    ('user_ids.active', '=', True),
                ]
            }
        else:
            res['domain'] = {
                'partner_id': []
            }
        return res


class SignSendRequest(models.TransientModel):
    _inherit = 'sign.send.request'

    def _get_employee_partner_domain(self):
        """
        Returns domain for filtering partners to internal users only.
        Used for Employee role signer assignment.
        """
        return [
            ('user_ids', '!=', False),
            ('user_ids.share', '=', False),
            ('user_ids.active', '=', True),
        ]

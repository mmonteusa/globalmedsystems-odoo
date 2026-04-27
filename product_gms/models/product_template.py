from odoo import models, fields
from random import randint

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _generate_barcode(self):
        """Generates a unique barcode by combining a random number and product ID."""
        return f"GMS-{randint(10000, 99999)}-{str(self.id).zfill(6)}"

    def create(self, vals):
        """Override the create method to set a barcode automatically."""
        if 'barcode' not in vals or not vals.get('barcode'):
            product = super(ProductTemplate, self).create(vals)
            product.barcode = product._generate_barcode()
            return product
        return super(ProductTemplate, self).create(vals)
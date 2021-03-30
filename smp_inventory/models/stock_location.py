# -*- coding: utf-8 -*-

from datetime import datetime
from dateutil import relativedelta
from odoo.exceptions import UserError

from odoo import api, fields, models, _
from odoo.osv import expression
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT


class StockLocation(models.Model):
    _inherit = "stock.location"
    _rec_name = 'code'

    code = fields.Char('Code', size=9, help="Short name used to identify your location")
    usage = fields.Selection(selection_add=[('reclassement', 'Reclassement')])
    _sql_constraints = [('unique_code', 'unique(code)', "The location code must be unique!!!")]

    @api.multi
    def name_get(self):
        result = []
        for s in self:
            if s.code:
                name = s.code + ' / ' + s.name
            else:
                name = s.name
            result.append((s.id, name))
        return result

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        """ search full name and barcode """
        args = args or []
        if operator == 'ilike' and not (name or '').strip():
            domain = []
        else:
            domain = ['|', '|', '|', ('barcode', operator, name), ('complete_name', operator, name),
                      ('name', 'ilike', name), ('code', 'ilike', name)]
        location_ids = self._search(expression.AND([domain, args]), limit=limit, access_rights_uid=name_get_uid)
        return self.browse(location_ids).name_get()

    def _should_be_valued(self):
        """ This method returns a boolean reflecting whether the products stored in `self` should
        be considered when valuating the stock of a company.
        """
        self.ensure_one()
        res = super(StockLocation, self)._should_be_valued()
        if self.usage == 'internal':
            return True
        return False

class Warehouse(models.Model):
    _inherit = "stock.warehouse"

    code = fields.Char('Short Name', required=True, size=9, help="Short name used to identify your warehouse")


# class WarehouseCategory(models.Model):
#     _name = "stock.warehouse.category"
#     _description = "Warehouse Category"
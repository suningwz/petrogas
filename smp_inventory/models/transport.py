from odoo import fields, models, api, _
from odoo.exceptions import UserError


class TransportPickingType(models.Model):
    _name = 'transport.picking.type'
    _description = 'Transport Picking Type'

    active = fields.Boolean('Active', default=True)
    name = fields.Char('Name', required=True)
    charge = fields.Many2one('product.product', string="Charge", domain=[('type', '=', 'service')], required=True)


class TransportPicking(models.Model):
    _name = 'transport.picking'
    _description = 'Cost Transport per route'

    name = fields.Char('Name', states={'done': [('readonly', True)]})
    active = fields.Boolean('Active', default=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')], string='Status', readonly=True, default='draft', states={'done': [('readonly', True)]})
    city_src = fields.Many2one('res.city', 'City Source', required=True, states={'done': [('readonly', True)]})
    city_dest = fields.Many2one('res.city', 'City Destination', required=True, states={'done': [('readonly', True)]})
    value = fields.Float(string="Value", digits=(10, 4), required=True, states={'done': [('readonly', True)]})
    type_id = fields.Many2one('transport.picking.type', required=True, states={'done': [('readonly', True)]})

    @api.multi
    def confirm(self):
        for record in self:
            record.state = 'done'

    @api.multi
    def draft(self):
        for record in self:
            record.state = 'draft'

    def get_transport_cost(self, stock_move_id):
        stock_move_id.ensure_one()
        if stock_move_id.picking_type_id.code == 'internal' \
                and stock_move_id.picking_type_id.internal_type == 'transfert':
            city_src = stock_move_id.origin_move_id.location_id
            city_dest = stock_move_id.location_id
        elif stock_move_id.picking_type_id.code == 'outgoing':
            city_src = stock_move_id.location_id.city_id
            city_dest = stock_move_id.picking_id.partner_id.city_id
        else:
            return False

        transport_cost_id = self.search(
            [('city_src', '=', city_src.id), ('city_dest', '=', city_dest.id)], limit=1)
        return transport_cost_id

    def create_transport_charge(self, stock_move_id):
        stock_move_id.ensure_one()
        transport_cost_id = self.get_transport_cost(stock_move_id)

        if transport_cost_id:

            if stock_move_id.picking_type_id.code == 'outgoing':
                supplier_id = stock_move_id.picking_id.transportor.id
            elif stock_move_id.picking_type_id.code == 'internal' \
                    and stock_move_id.picking_type_id.internal_type == 'transfert':
                supplier_id = stock_move_id.internal_picking.transportor.id
            else:
                supplier_id = False

            charge_id = self.env['stock.move.charges'].create([{
                'stock_move_id': stock_move_id.id,
                'rubrique_id': transport_cost_id.type_id.charge.id,
                'cost_unit': transport_cost_id.value,
                'cost': transport_cost_id.value * stock_move_id.product_qty,
                'supplier': supplier_id
            }])
            return charge_id

    def create_account_move_line(self, stock_move_id):
        transport_charge_id = self.create_transport_charge(stock_move_id)
        if transport_charge_id:
            # debit_line, credit_line = transport_charge_id.get_move_charge_accounting_entry()
            return transport_charge_id.create_account_move_line_from_charge()
        return False


class StockLocation(models.Model):
    _inherit = 'stock.location'

    city_id = fields.Many2one('res.city', 'City')


class StockMove(models.Model):
    _inherit = 'stock.move'

    def create_transport_charge(self):
        self.ensure_one()
        return self.env['transport.picking'].create_transport_charge(self)

    def create_transport_account_move_line(self):
        self.ensure_one()
        return self.env['transport.picking'].create_account_move_line(self)

    def has_transport_charge(self):
        self.ensure_one()
        res = False
        if self.picking_type_id.code == 'outgoing':
            if self.picking_id.transport_type:
                res = True
        if self.picking_type_id.code == 'internal' \
                and self.picking_type_id.internal_type == 'transfert':
            if self.internal_picking_id.transport_type:
                res = True
        return res


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_transportor = fields.Boolean('Is a Transportor')


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    transport_type = fields.Many2one('transport.picking.type', 'Transport Type')
    # transportor = fields.Many2one('res.partner', 'Transportor', domain=[('is_transportor', '=', True)])
    transportor = fields.Many2one('res.partner', 'Transportor')


class StockMoveCharges(models.Model):
    _inherit = 'stock.move.charges'

    supplier = fields.Many2one('res.partner', 'Vendor', ondelete='restrict')

    def create_account_move_line_from_charge(self):
        """•	Comment déterminer le compte :
            * Est-ce que la charge est inclus dans le cout du stock de destination.
            * Oui, alors compte de provision.
            * Non alors compte de provision et compte de dépense.
            * Comment détermine t’on le signe de la balance :
            * Ecriture de provision toujours au crédit sauf si il s’agit d’un retour
        """
        self.ensure_one()
        if self.account_move_line_ids:
            raise UserError(_("""Charge 's account entries already exist!!!"""))

        expense, income = self._get_charge_account()
        cancelled_charge = False
        if self.stock_move_id.origin_returned_move_id:
            cancelled_charge = True

        value = - self.cost if cancelled_charge else self.cost
        res = {}
        ref = self.stock_move_id.reference
        provision_aml = {
            'name': self.rubrique_id.name,
            'ref': ref + ' / ' + self.rubrique_id.name,
            # 'partner_id': self.partner_id.id if self.partner_id else None,
            'product_id': self.product_id.id,
            'quantity': self.product_qty,
            'product_uom_id': self.product_id.uom_id.id,
            'account_id': income,
            'debit': abs(value) if value < 0 else 0,
            'credit': abs(value) if value > 0 else 0,
            'charge_id': self.id,
        }
        res['provision']= provision_aml

        trigger_cost_valuation = self.stock_move_id.picking_type_id.trigger_cost_valuation
        if not trigger_cost_valuation:
            expense_line = provision_aml.copy()
            expense_line['account_id'] = expense
            expense_line['debit'] = abs(value) if value > 0 else 0
            expense_line['credit'] = abs(value) if value < 0 else 0
            res['expense'] = expense_line
        return res
# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from odoo.addons import decimal_precision as dp
from odoo.tools import float_is_zero, float_round
from collections import defaultdict


class AccountInvoiceLine(models.Model):
    _inherit = 'account.invoice.line'

    bulletin_line_ids = fields.One2many('bulletin.line', 'invoice_line_id')


class BulletinBulletin(models.Model):
    _name = 'bulletin.bulletin'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    _description = "Bulletin de régularisation"

    name = fields.Char('Sequence', default="/", readonly=True)
    reference = fields.Char(string="Reference")
    date_accounting = fields.Date('Accounting Date', default=fields.Date.today())
    date_start = fields.Date('Date From', default=fields.Date.today())
    date_end = fields.Date('Date To', default=fields.Date.today())
    product_id = fields.Many2one('product.product', 'Product', domain=[('type', '=', 'product')])
    regime_id = fields.Many2one('regime.douanier', 'Customs Duties')
    product_qty = fields.Float("Storage Quantity", compute='_compute_product_qty', store=True, readonly=True)
    location_id = fields.Many2one('stock.location', 'location_id', domain=[('usage', '=', 'internal')])
    # stock_move_ids = fields.Many2one('stock.move', 'bulletin_id', 'Opération', domain=[('state', '=', 'done')])
    stock_move_ids = fields.Many2many('stock.move', 'rel_bulletin_stock_move', 'bulletin_id', 'stock_move_id',domain=[('state', '=', 'done')])
    state = fields.Selection([('draft', 'Draft'), ('open', 'Open'), ('done', 'Done'), ('cancel', 'Cancel')],
                             default='draft')
    picking_type_ids = fields.Many2many('stock.picking.type', 'rel_bulletin_picking_type', 'bulletin_id',
                                        'picking_type_id')
    bulletin_line_ids = fields.One2many('bulletin.line', 'bulletin_id', 'Regularizable Charges', copy=False)
    charge_slip_line_ids = fields.One2many('charge.slip.line', 'bulletin_id', 'Charge Slip Line', copy=False)


    @api.model
    def create(self, vals):
        vals['name'] = self.env['ir.sequence'].get('bulletin.bulletin') or '/'
        res_id = super(BulletinBulletin, self).create(vals)
        return res_id

    # @api.depends('stock_move_ids')
    def update_bulletin_line(self):
        for bulletin_line_id in self.bulletin_line_ids:
            # est ce que le stock_move_id a un stock_move_charge pouvant être incopérer dans bulletin_line_id
            # on verifie si le stock_move_id n'est pas dans les charge existant
            bl_smc = bulletin_line_id.stock_move_charge_ids
            all_smc = self.stock_move_ids.stock_move_charges_ids.filtered(lambda x: x.rubrique_id == bulletin_line_id.rubrique_id)

            # if bulletin_line_id.rubrique_id in self

    @api.multi
    def bulletin_cancel(self):
        """ On doit annuler les factures"""
        # TODO: Add access control
        for record in self:
            for line in record.bulletin_line_ids:
                if line.invoice_id and line.invoice_id.state not in ['cancel']:
                    raise exceptions.UserError(_(
                        'You must cancel or destroy the invoice %s. Ensure the write-off account move is cancelled!') % line.invoice_id.number)
            # record.bulletin_line_ids.mapped('invoice_id').action_invoice_cancel()
            record.bulletin_line_ids.mapped('stock_move_charge_ids').write({'regulated_amount':0.0})
            record.bulletin_line_ids.unlink()
            # record.stock_move_ids = [(3, x.id, _) for x in record.stock_move_ids]
            record.state = 'cancel'


    @api.multi
    def open(self):
        self.ensure_one()
        if self.name == '/':
            self.name = self.env['ir.sequence'].next_by_code('bulletin.bulletin')
        self.create_group_charges()
        self.state = 'open'

    def done(self):
        # TODO regulariser les PC-c
        stock_move_charge_ids = self.bulletin_line_ids.stock_move_charge_ids

        # """ Stock.move.charge : MAJ du champ Value des MAJ"""
        for smc in stock_move_charge_ids:
            smc.previous_amount = smc.cost
            smc.cost = smc.regulated_amount


        """"""
        for buline in self.bulletin_line_ids:
            buline.value = buline.regulated_amount
            # buline.value = sum(buline.stock_move_charge_ids.mapped('cost'))

        """ valeur  Total = value +  stock_landing"""
        stock_move_ids = stock_move_charge_ids.mapped('stock_move_id')

        """ Maj à jours des champs value et des PC"""
        stock_move_ids.update_stock_move_value()
        stock_move_ids.update_account_entry_move()

        # TODO Créer Facture
        for buline in self.bulletin_line_ids.filtered(lambda x: x.to_invoice):
            buline.create_invoice()

        self.state = 'done'
        return True

    @api.multi
    def open_wizard(self):
        self.ensure_one()
        # stock_move_ids = self.env['stock.move'].search([('product_id', '=', self.product_id.id),
        #                                                 ('state', '=', 'done'),
        #                                                 ('picking_type_id', 'in', self.picking_type_ids.ids)
        #                                                 ])
        domain = [('picking_type_id', 'in', self.picking_type_ids.ids), ('product_id', 'in', self.product_id.ids)]
        if self.date_start:
            domain += [('date_expected', '>=', self.date_start)]

        if self.date_end:
            domain += [('date_expected', '<=', self.date_end)]

        if self.location_id:
            domain += [('location_id', '=', self.location_id.id)]

        stock_move_ids = self.env['stock.move'].search(domain) - self.stock_move_ids

        if stock_move_ids:
            BulletinWizard = self.env['bulletin.wizard']
            wiz = BulletinWizard.create({
                'stock_move_ids': [(4, p.id) for p in stock_move_ids],
                'bulletin_id': self.id})
            view = self.env.ref('smp_bulletin.view_bulletin_wizard')
            action = BulletinWizard.get_formview_action()
            action['res_id'] = wiz.id
            action['view_id'] = view.id
            action['target'] = 'new'
            return action

    @api.multi
    @api.depends('stock_move_ids')
    def _compute_product_qty(self):
        for r in self:
            if r.stock_move_ids:
                r.product_qty = sum([move.product_qty for move in r.stock_move_ids])
            else:
                r.product_qty = 0

    @api.multi
    @api.onchange('stock_move_ids')
    def onchange_stock_move_ids(self):
        self.ensure_one()
        if self.stock_move_ids:
            self.product_qty = sum([move.product_qty for move in self.stock_move_ids])
        else:
            self.product_qty = 0

    @api.multi
    def create_group_charges(self):
        self.bulletin_line_ids.unlink()
        res = defaultdict(lambda: {'value': 0.0, 'product_qty': 0.0, 'stock_move_charge_ids': []})
        for move in self.stock_move_ids:
            for charge in move.charges_ids.filtered(lambda x: not x.bulletin_line_id):
                res[charge.rubrique_id]['product_qty'] += charge.product_qty
                res[charge.rubrique_id]['value'] += charge.cost
                res[charge.rubrique_id]['stock_move_charge_ids'] += [(4, charge.id)]
                if not res[charge.rubrique_id].get('rubrique_id', False):
                    res[charge.rubrique_id]['rubrique_id'] = charge.rubrique_id.id
                    res[charge.rubrique_id]['bulletin_id'] = self.id

        for k, v in res.items():
            stock_move_charge_ids = v.pop('stock_move_charge_ids', None)
            line_id = self.bulletin_line_ids.create(v)
            line_id.stock_move_charge_ids = stock_move_charge_ids

    @api.multi
    def compute_rule_all_bulletin_line(self):
        self.create_group_charges()
        # self.bulletin_line_ids.compute_rule_bulletin_line_charge()

    @api.multi
    def create_invoice(self):
        key_dict = {}
        AI = self.env['account.invoice']
        AIL = self.env['account.invoice.line']
        journal_id = self.env['account.journal'].search([('type', '=', 'purchase')])[0]
        for buline in self.bulletin_line_ids.filtered(lambda x: x.to_invoice):
            # if buline.partner_id.id in key_dict:
            # key_dict[buline.partner_id.id][buline.charge_rule_category_id][buline.charge_rule_category_id][buline.rubrique_id] =
            # key_dict[buline.partner_id.id] [buline.id]= buline.prepare_invoice_line()
            invoice_id = AI.create([{
                'date': self.date_accounting,
                'date_invoice':self.date_accounting,
                'currency_id': self.env.user.company_id.currency_id.id,
                'journal_id': journal_id.id,
                'company_id': self.env.user.company_id.id,
                'partner_id': self.env.user.company_id.id,
                'type': 'in_invoice',
                'reference': buline.bulletin_id.sequence,
            }])

            invoice_line_id = AIL.create([{
                "name": buline.bulletin_id.product_id.product_tmpl_id.name + ' - ' + buline.charge_rule_category_id.name,
                "product_id": buline.rubrique_id.id,
                "price_unit": buline.value / buline.product_qty,
                "quantity": buline.product_qty,
                "uom_id": buline.bulletin_id.product_id.uom_id.id,
                "invoice_id": invoice_id.id,
                "account_id": buline.rubrique_id.property_account_income_id.id
            }])

            buline.invoice_id = invoice_id
            invoice_id.action_invoice_open()
            charges_aml_ids = buline.stock_move_charge_ids.mapped('account_move_line_ids').filtered(lambda x: x.account_id == invoice_line_id.account_id)
            assert charges_aml_ids
            invoice_aml_id = invoice_line_id.move_line_ids.filtered(lambda x: x.account_id == invoice_line_id.account_id)
            invoice_aml_id.ensure_one()
            assert sum(charges_aml_ids.mapped('balance')) == -sum(invoice_aml_id.mapped('balance'))
            charges_aml_ids += invoice_aml_id
            charges_aml_ids.reconcile(writeoff_acc_id=False, writeoff_journal_id=False)


class BulletinLine(models.Model):
    _name = 'bulletin.line'
    _description = "Ligne de bulletin de régularisation"

    bulletin_id = fields.Many2one('bulletin.bulletin', 'Bulletin', ondelete='cascade', required=True)
    product_id = fields.Many2one('product.product', 'Product', related="bulletin_id.product_id", ondelete='cascade',
                                 required=True)
    rubrique_id = fields.Many2one('product.product', 'Charge', required=True, readonly=True)
    product_qty = fields.Float("Quantity in storage unit", readonly=True)
    value = fields.Float("Current cost", digits=dp.get_precision('Product Price'), readonly=True)
    regulated_amount = fields.Float('Computed cost', digits=dp.get_precision('Product Price'), readonly=True)
    invoiced_amount = fields.Float('Invoiced cost', digits=dp.get_precision('Product Price'))
    to_invoice = fields.Boolean('To Invoice')
    invoice_id = fields.Many2one('account.invoice', 'Invoice', readonly=True , ondelete="set null")
    invoice_line_id = fields.Many2one('account.invoice.line', 'Invoice Line', readonly=True , ondelete="set null")
    partner_id = fields.Many2one('res.partner', 'Supplier', domain=[('supplier', '=', 'true')])
    charge_rule_category_id = fields.Many2one('charge.rule.category', 'Regularization Template')
    stock_move_charge_ids = fields.One2many('stock.move.charges', 'bulletin_line_id', 'Cost Lines')
    charge_slip_line_ids = fields.One2many('charge.slip.line', 'bulletin_line_id', 'Charge Slip Line')
    state = fields.Selection(related='bulletin_id.state', store=True,  track_visibility='always')
    write_off_line_move_id = fields.Many2one('account.move.line', 'Write off account move line')


    @api.multi
    def name_get(self):
        result = []
        for s in self:
            name = s.bulletin_id.name + ' - ' + ', '.join(set(s.stock_move_charge_ids.mapped('product_id.default_code'))) + ' - ' + s.rubrique_id.name
            result.append((s.id, name))
        return result

    @api.multi
    def get_charge_slip_line(self):
        self.ensure_one()

        # if self.charge_slip_line_ids:
        self.charge_slip_line_ids.unlink()
        charge_slip_line_ids = self.charge_rule_category_id.charge_rule_ids
        line_ids = [{'bulletin_line_id': self.id,
                     'bulletin_id': self.bulletin_id.id,
                     'charge_rule_id': rule.id} for rule in charge_slip_line_ids]
        charge_slip_line_ids = self.charge_slip_line_ids.create(line_ids)
        return charge_slip_line_ids

    def open_table(self, input_line):
        action = self.env.ref('smp_bulletin.view_charge_slip_line_action')
        action = action.read()[0]
        action['domain'] = [('id', 'in', input_line.ids)]
        action['view_id'] = 'view_charge_slip_line_tree'
        action['view_mode'] = 'tree'
        action['view_type'] = 'tree'
        # action['context'] = {'default_bulletin_line_id': self.id, ''}
        return action

    @api.multi
    def compute_rule_bulletin_line_charge(self):
        for bulletin_line in self:
            regulated_amount = 0.0
            for stock_move_charge in bulletin_line:
                # dict_value = {'stock_move_ids': bulletin_line.stock_move_charge_ids.mapped('stock_move_id')}
                dict_value = {'stock_move_ids': stock_move_charge.stock_move_id}
                for charge_slip_line in bulletin_line.charge_slip_line_ids.sorted(lambda r: r.sequence):
                    # TODO: Check si element nécessaire au calcule sont dans le dict
                    result = charge_slip_line.compute_rule(dict_value)
                    charge_slip_line.amount += result[0]
                    dict_value[charge_slip_line.charge_rule_id.code] = charge_slip_line.amount
                    if charge_slip_line.is_mandatory_output:
                        regulated_amount += charge_slip_line.amount
            bulletin_line.regulated_amount += regulated_amount

    @api.multi
    def open_wizard1(self):
        self.ensure_one()
        view = self.env.ref('smp_bulletin.view_charge_slip_line_wizard')
        charge_slip_line_ids = self.get_charge_slip_line()
        charge_slip_line_ids = charge_slip_line_ids.filtered(lambda x: x.is_mandatory_input)
        if charge_slip_line_ids:
            wiz = self.env['charge.slip.line.wizard'].create({
                'charge_slip_line_ids': [(4, p.id) for p in charge_slip_line_ids],
                'amount': 0.0,
            })
            return {
                'name': _('Charge Slip Line - Mandatory Input Entry?'),
                'type': 'ir.actions.act_window',
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'charge.slip.line.wizard',
                'views': [(view.id, 'form')],
                'view_id': view.id,
                'target': 'new',
                'res_id': wiz.id,
                # 'context': self.env.context,
            }

    @api.multi
    def open_wizard(self):
        self.ensure_one()
        if not self.charge_rule_category_id:
            raise exceptions.UserError(_("Veuillez indiquer le modèle de régularisation à appliquer!!!"))
        charge_slip_line_ids = self.get_charge_slip_line()
        charge_slip_line_ids = charge_slip_line_ids.filtered(lambda x: x.is_mandatory_input)
        if charge_slip_line_ids:
            ChargeSlipWizard = self.env['charge.slip.line.wizard']
            view = self.env.ref('smp_bulletin.view_charge_slip_line_wizard')
            wiz = ChargeSlipWizard.create({
                'charge_slip_line_ids': [(4, p.id) for p in charge_slip_line_ids],
                'amount': 0.0,
            })
            action = ChargeSlipWizard.get_formview_action()
            action['res_id'] = wiz.id
            action['view_id'] = view.id
            action['target'] = 'new'
            return action

    @api.multi
    def create_invoice(self):
        key_dict = {}
        AI = self.env['account.invoice']
        AIL = self.env['account.invoice.line']
        journal_id = self.env['account.journal'].search([('type', '=', 'purchase')])[0]
        # bullconf = self.env['bulletin.configuration'].search([])[0]
        bullconf = self.env.ref('smp_bulletin.bulletin_main_configuration')
        writeoff_acc_id = bullconf.dif_reconciliation_account
        writeoff_journal_id = bullconf.dif_reconciliation_journal


        for buline in self.filtered(lambda x: x.to_invoice):
            invoice_id = AI.create([{
                'date': buline.bulletin_id.date_accounting,
                'date_invoice': buline.bulletin_id.date_accounting,
                'currency_id': self.env.user.company_id.currency_id.id,
                'journal_id': journal_id.id,
                'company_id': self.env.user.company_id.id,
                'partner_id': buline.partner_id.id,
                'type': 'in_invoice',
                'reference': buline.bulletin_id.name,
            }])
            # precision_digits = dp.get_precision('Product Price')
            # precision_rounding = dp.get_precision('Product Price')
            # price_unit = float_round(buline.value / buline.product_qty, precision_digits=precision_digits)
            #
            # assert float_is_zero(price_unit * buline.product_qty - buline.value, precision_digits=precision_digits)
            invoice_line_id = AIL.create([{
                "name": buline.bulletin_id.product_id.product_tmpl_id.name + ' - ' + buline.charge_rule_category_id.name,
                "product_id": buline.rubrique_id.id,
                "price_unit": buline.invoiced_amount,
                # "price_unit": buline.value,
                "quantity": 1,
                # "quantity": buline.product_qty,
                "uom_id": buline.bulletin_id.product_id.uom_id.id,
                "invoice_id": invoice_id.id,
                "account_id": buline.rubrique_id.property_account_income_id.id
            }])

            buline.invoice_id = invoice_id
            buline.invoice_line_id = invoice_line_id

            invoice_id.action_invoice_open()
            self.invalidate_cache()
            # # buline.stock_move_charge_ids.mapped('account_move_line_ids').invalidate_cache()
            charges_aml_ids = buline.stock_move_charge_ids.mapped('account_move_line_ids').filtered(lambda x: x.account_id == invoice_line_id.account_id)
            assert charges_aml_ids
            invoice_aml_id = invoice_line_id.invoice_id.move_id.line_ids.filtered(lambda x: x.account_id == invoice_line_id.account_id)
            invoice_aml_id.ensure_one()
            # bal_charge_aml_ids = sum(charges_aml_ids.mapped('balance'))
            # bal_invoice_aml_id = -sum(invoice_aml_id.mapped('balance'))
            # assert bal_charge_aml_ids == bal_invoice_aml_id
            charges_aml_ids += invoice_aml_id
            charges_aml_ids.with_context(comment=buline.bulletin_id.name).reconcile(writeoff_acc_id=writeoff_acc_id, writeoff_journal_id=writeoff_journal_id)
            write_off_line = buline.find_writeoff_account_move_line_id()
            if write_off_line:
                write_off_line_move_id = write_off_line.mapped('move_id')
                self.write_off_line_move_id = write_off_line_move_id.id

    @api.multi
    def find_writeoff_account_move_line_id(self):
        self.ensure_one()
        invoice_id = self.invoice_id
        invoice_id.ensure_one()
        invoice_line_id = invoice_id.invoice_line_ids
        invoice_line_id.ensure_one()

        charge_move_line_ids = self.stock_move_charge_ids.mapped('account_move_line_ids').filtered(lambda r: r.account_id == invoice_line_id.account_id)

        full_reconcile_id = charge_move_line_ids.mapped('full_reconcile_id')
        reconcile_line_ids = full_reconcile_id.reconciled_line_ids

        invoice_move_line_id = reconcile_line_ids.filtered(lambda r: r.move_id == invoice_id.move_id)

        writeoff_account_move_line_id = (reconcile_line_ids - invoice_move_line_id) - charge_move_line_ids

        if writeoff_account_move_line_id:
            writeoff_account_move_line_id.ensure_one()
            return writeoff_account_move_line_id
        return False


class ChargeSlipLine(models.Model):
    _name = 'charge.slip.line'
    _description = 'Bulletin de calcul de charge'
    _order = "bulletin_line_id asc, sequence asc"

    bulletin_id = fields.Many2one('bulletin.bulletin', 'Bulletin', ondelete='cascade', required=True)
    bulletin_line_id = fields.Many2one('bulletin.line', 'Ligne de bulletin', ondelete='cascade', required=True)
    charge_rule_id = fields.Many2one('charge.rule', 'Regle de calcul', required=True)
    charge_rule_category_id = fields.Many2one('charge.rule.category', 'Catégorie des regle de calcul',
                                              related='charge_rule_id.category_id', required=True)
    sequence = fields.Integer('Sequence', related='charge_rule_id.sequence', store=True)
    # amount = fields.Float('Amount', digits=dp.get_precision('Product Price'))
    amount = fields.Float('Amount', digits=(10, 6))
    is_mandatory_input = fields.Boolean('Mandatory Input', related='charge_rule_id.is_mandatory_input')
    is_mandatory_output = fields.Boolean('Mandatory Output', related='charge_rule_id.is_mandatory_output')

    # TODO should add some checks on the type of result (should be float)
    @api.one
    def compute_rule(self, localdict):
        """
        :param localdict: dictionary containing the environement in which to compute the rule
        :return: returns a tuple build as the base/amount computed, the quantity and the rate
        :rtype: (float, float, float)
        """
        rule = self.charge_rule_id

        if rule.is_mandatory_input:
            return self.amount

        elif rule.amount_select == 'fix':
            try:
                return self.amount_fix
            except:
                raise exceptions.ValidationError(
                    _('Wrong quantity defined for salary rule %s (%s).') % (rule.name, rule.code))
        elif rule.amount_select == 'percentage':
            try:
                ratio = rule.amount_percentage / 100
                amount_percentage_base = eval(rule.amount_percentage_base, localdict)
                return ratio * amount_percentage_base
            except:
                raise exceptions.ValidationError(
                    _('Wrong percentage base or quantity defined for salary rule %s (%s).') % (rule.name, rule.code))
        else:
            try:
                return eval(rule.amount_python_compute, localdict)
            except:
                raise exceptions.ValidationError(
                    _('Wrong python code defined for salary rule %s (%s).') % (rule.name, rule.code))


class ChargeSlipLineWizard(models.TransientModel):
    _name = 'charge.slip.line.wizard'
    _description = 'Bulletin de calcul de charge'

    charge_slip_line_ids = fields.Many2many('charge.slip.line', string="Element de recalcul")

    @api.multi
    def process(self):
        bulletin_line_ids = self.charge_slip_line_ids.mapped('bulletin_line_id')
        if bulletin_line_ids:
            for bulletin_line in bulletin_line_ids:
                bulletin_line.stock_move_charge_ids.compute_rule_stock_move_charge()
                bulletin_line.regulated_amount = sum(bulletin_line.stock_move_charge_ids.mapped('regulated_amount'))


class BulletinWizard(models.TransientModel):
    _name = 'bulletin.wizard'

    bulletin_id = fields.Many2one('bulletin.bulletin', 'bulletin_id')
    stock_move_ids = fields.Many2many('stock.move', domain=[('state', '=', 'done')])

    @api.multi
    def process(self):
        self.ensure_one()
        self.bulletin_id.stock_move_ids = [(4, x.id) for x in self.stock_move_ids]


class BulletinConfiguration(models.Model):
    _name = 'bulletin.configuration'
    _description = "Cost landing amount regularization configuration "

    dif_reconciliation_account = fields.Many2one('account.account', 'Reconciliation account', help="""Account entries for reconciliation difference.""")
    dif_reconciliation_journal = fields.Many2one('account.journal', 'Reconciliation journal', help="""Entries journal for reconciliation difference.""")


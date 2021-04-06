# -*- coding: utf-8 -*-

from odoo import models, fields, api, exceptions, _
from collections import defaultdict


class ChargeRule(models.Model):
    _name = 'charge.rule'
    _description = "Indicate charge rule method"
    # _parent_store = True
    _parent_name = "parent_rule_id"  # optional if field is 'parent_id'

    AMOUNT_PYTHON_COMPUTE_TEXT = """ 
    # Available variables:
    #----------------------
    # stock_move_ids': stock_move_ids,
    # stock_move_id': record.mapped('stock_move_id'),
    # product_qty': sum(record.mapped('product_qty'))}
    # charges_ids: all stock move charges  
    """


    # parent_path = fields.Char(index=True)
    charge_id = fields.Many2one('product.product', 'Charge', required=True)
    parent_rule_id = fields.Many2many('charge.rule', 'rel_charges_rules_charge_rule', 'charge_rule_id','parent_rule_id', string='Parent Charge Rule')
    # parent_rule_id = fields.Many2one('charge.rule', 'Parent Charge Rule')
    name = fields.Char('Label', related='charge_id.product_tmpl_id.name', readonly=True)
    code = fields.Char('Code', related='charge_id.product_tmpl_id.default_code', readonly=True, required=True, help="The code of salary rules can be used as reference in "
                                                            "computation of other rules. In that case, it "
                                                            "is case sensitive.")
    sequence = fields.Integer('Sequence', compute='compute_sequence', required=True, help='Use to arrange calculation sequence', store=True, default=0)
    quantity = fields.Char('Quantity', size=256,
                           help="It is used in computation for percentage and fixed amount.For e.g. A rule for Meal "
                                "Voucher having fixed amount of 1€ per worked day can have its quantity defined "
                                "in expression like worked_days.WORK100.number_of_days.")
    category_id = fields.Many2one('charge.rule.category', 'Category', required=True)
    active = fields.Boolean('Active', help="If the active field is set to false, it will "
                                           "allow you to hide the salary rule without removing it.", default=True)
    amount_select = fields.Selection([('percentage', 'Percentage (%)'), ('fix', 'Fixed Amount'), ('code', 'Python Code')],
                                     'Amount Type',  required=True, help="The computation method for the rule amount")
    amount_fix = fields.Float('Fixed Amount', digits=(2, 3))
    amount_percentage = fields.Float('Percentage (%)', digits=(3, 1),
                                     help='For example, enter 50.0 to apply a percentage of 50%')
    amount_python_compute = fields.Text('Python Code', default=AMOUNT_PYTHON_COMPUTE_TEXT)
    amount_percentage_base = fields.Char('Percentage based on', size=1024, required=False, readonly=False,
                                          help='result will be affected to a variable')
    # child_ids = fields.One2many('charge.rule', 'parent_rule_id', 'Child Charge Rule', readonly=True)
    is_mandatory_input = fields.Boolean('Mandatory Input', default=False)
    is_mandatory_output = fields.Boolean('Mandatory Output', compute='compute_is_mandatory_output', default=False)


    @api.one
    @api.constrains('parent_rule_id')
    def _check_hierarchy(self):
        if not self._check_m2m_recursion('parent_rule_id'):
        # if not self._check_recursion():
            raise exceptions.ValidationError(_('You cannot create recursive rule!'))

    @api.multi
    @api.depends('parent_rule_id')
    def compute_sequence(self):
        for r in self:
            if r.parent_rule_id:
                r.sequence = max(r.parent_rule_id.mapped('sequence')) + 1
            else:
                r.sequence = 0

    @api.multi
    @api.depends('category_id')
    def compute_is_mandatory_output(self):
        for r in self:
            r.is_mandatory_output = False
            if r.category_id and r.category_id.charge_rule_id == r:
                r.is_mandatory_output = True

    @api.multi
    def toggle_active(self):
        """ Inverse the value of the field ``active`` on the records in ``self``. """
        for record in self:
            record.active = not record.active

   #TODO should add some checks on the type of result (should be float)
    @api.one
    def compute_rule(self, localdict):
        """
        :param localdict: dictionary containing the environement in which to compute the rule
        :return: returns a tuple build as the base/amount computed, the quantity and the rate
        :rtype: (float, float, float)
        """
        rule = self
        if rule.is_mandatory_input:
            return self.amount

        elif rule.amount_select == 'fix':
        # if rule.amount_select == 'fix':
            a = eval(str(rule.quantity), localdict)
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


class ChargeRuleCategory(models.Model):
    _name = 'charge.rule.category'
    _description = "Catégorie de règle de charge"

    active = fields.Boolean(default=True, help="Set active to false to hide the modele without removing it.")
    name = fields.Char('Nom', required=True)
    code = fields.Char('Code', required=True)
    charge_rule_id = fields.Many2one('charge.rule', 'Charge Rule')
    charge_rule_ids = fields.One2many('charge.rule', 'category_id', string='Charge Rule List')

    _sql_constraints = [('unique_name', 'UNIQUE(name)', 'The name must be unique!!'),
                        ('unique_code', 'UNIQUE(code)', 'The code must be unique!!')]


    @api.multi
    def copy_data(self, default=None):
        if default is None:
            default = {}
        # if 'charge_rule_ids' not in default:
        default['name'] = self.name + ' - Copie'
        default['code'] = self.code + ' - Copie'
        default['charge_rule_ids'] = [(0, 0, line.copy_data()[0]) for line in self.charge_rule_ids]
        return super(ChargeRuleCategory, self).copy_data(default)

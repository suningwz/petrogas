# -*- coding: utf-8 -*-

from datetime import timedelta, datetime, date
import calendar as cal
import time
from dateutil.relativedelta import relativedelta

from odoo import fields, models, api, _, exceptions
from odoo.osv import expression

from odoo.exceptions import ValidationError, UserError, RedirectWarning
from odoo.tools.misc import DEFAULT_SERVER_DATE_FORMAT
from odoo.tools.float_utils import float_round, float_is_zero
from odoo.tools import date_utils
from dateutil import relativedelta

class AccountFiscalYear(models.Model):
    _inherit = 'account.fiscal.year'

    _order = 'date_from desc'


    opening_journal_id = fields.Many2one('account.journal', string='Opening Journal', domain=[('type', '=', 'open')])
    period_ids = fields.One2many('account.period', 'fiscalyear_id', string="Account Periods")
    state = fields.Selection([('open', 'Open'), ('done', 'Closed')], 'State', default='open')
    opening_move_ids = fields.Many2many('account.move', string="Opening Moves")



    @api.multi
    def create_month_periods(self):
        self.ensure_one()
        year = self.date_from.year
        res=[]
        for i in range(1,13):
            date_from = date(year, i, 1)
            date_to = date(year, date_from.month, cal.monthrange(year, date_from.month)[1])
            month = len(str(date_from.month)) == 1 and '0'+str(date_from.month) or str(date_from.month)
            name = "%s/%s" % (month, year)
            self.env['account.period'].create({'date_from': date_from, 'date_to': date_to, 'name': name, 'code': name, 'fiscalyear_id': self.id})

    @api.model
    def find(self, dt=None):
        if not dt:
            dt = fields.date.today()
        company_id = self.env.context.get('company_id', False)
        if not company_id:
            company_id = self.env.user.company_id.id
        domain = [('date_from', '<=', dt), ('date_to', '>=', dt),('company_id', '=', company_id)]
        fiscalyear_id = self.search(domain)
        if not fiscalyear_id:
            raise exceptions.UserError(_("""'There is no fiscal year defined for the date %s.\n Please create one from the configuration of the accounting menu.'""") % dt)
        assert len(fiscalyear_id) == 1
        return fiscalyear_id


    @api.multi
    def _get_opening_move_ids(self):
        opening_move_ids = self.env['account.move'].search([('journal_id', '=', self.opening_journal_id.id), ('date', '=', self.date_from)])
        return opening_move_ids

    @api.onchange('opening_journal_id')
    def set_opening_move_ids(self):
        self.opening_move_ids = [(5, )]
        if self.opening_journal_id:
            opening_move_ids = self._get_opening_move_ids()
            if opening_move_ids:
                self.opening_move_ids = [(4, x.id) for x in opening_move_ids]


class AccountPeriod(models.Model):
    _name = 'account.period'
    _description = 'Account Periods'

    _order = 'date_from asc'

    name = fields.Char(string='Name', required=True, size=128)
    code = fields.Char(string='Code', required=True, size=8, readonly=True)
    date_from = fields.Date(string='Start Date', required=True,
        help='Start Date, included in the period.')
    date_to = fields.Date(string='End Date', required=True,
        help='Ending Date, included in the period.')
    company_id = fields.Many2one('res.company', string='Company', required=True,
        default=lambda self: self.env.user.company_id)
    fiscalyear_id = fields.Many2one('account.fiscal.year', 'Fiscal Year', required=True)
    state = fields.Selection([('open', 'Open'), ('done', 'Closed')], 'State', default='open')
    company_id = fields.Many2one('res.company', related='fiscalyear_id.company_id',  string='Company', store=True, readonly=True )


    @api.constrains('date_from', 'date_to')
    def _check_duration(self):
        if self.date_to < self.date_from:
            return False
        return True

    _constraints = [
        (_check_duration, _('Error!\nThe start date of a fiscal year must precede its end date.'), ['date_from','date_to'])
    ]

    _sql_constraints = [
        ('name_company_uniq', 'unique(name, company_id)', 'The name of the period must be unique per company!'),
        ('code_company_uniq', 'unique(code, company_id)', 'The code of the period must be unique per company!'),
    ]

    # @api.multi
    # def _check_db_exist(self):
    #     self.ensure_one()
    #
    #     db_list = self.get_db_list(self.host, self.port)
    #     if self.name in db_list:
    #         return True
    #     return False
    #
    # _constraints = [(_check_db_exist, _('Error ! No such database exists!'), [])]

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        """ search full name and barcode """
        args = args or []
        if operator == 'ilike' and not (name or '').strip():
            domain = []
        else:
            domain = ['|', ('code', operator, name), ('name', operator, name)]
        period_ids = self._search(expression.AND([domain, args]), limit=limit, access_rights_uid=name_get_uid)
        return self.browse(period_ids).name_get()

    @api.model
    def find_period_from_date(self, dt=False):
        if not dt:
            dt = fields.Date.today()

        month = len(str(dt.month)) == 1 and '0' + str(dt.month) or str(dt.month)
        code = "%s/%s" % (month, dt.year)
        period_id = self.search([('code', '=', code)])
        if not period_id:
            raise exceptions.UserError(_("""Any account period found for the date %.""") % date)
        assert len(period_id) == 1

    @api.multi
    def next(self, period, step=1):
        period_ids = self.search([('date_from', '>', period.date_from + relativedelta(months=+step))])
        if not period_ids:
            raise exceptions.UserError(_("""Any period has been found after the period %s.""") % self.code)
        assert len(period_ids) == 1
        return period_ids


class AccountJournal(models.Model):
    _inherit = "account.journal"

    # is_opening_journal = fields.Boolean('Is Opening Journal', help='Indicate that this journal is only')
    type = fields.Selection(selection_add=[('open', 'Opening Journal')])

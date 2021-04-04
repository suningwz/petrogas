# © 2019 Disruptsol
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AccountMoveTransfertWizard(models.TransientModel):
    _name = 'account.move.transfert.wizard'
    _description = 'Transfert account move line to another account'


    date = fields.Date('Date', default=fields.Date.today())
    journal_id_src = fields.Many2one('account.journal', string="Source journal", domain=[('type', 'in', ['cash', 'bank'])], required=True)
    account_ids = fields.Many2many('account.account', string="Account")
    journal_id_dest = fields.Many2one('account.journal', string="Destination journal", domain=[('type', 'in', ['cash', 'bank'])], required=True)
    account_move_line_ids = fields.Many2many('account.move.line')
    transfert_type = fields.Selection((('unique', 'By account move line'), ('global', 'Global')),
                                      string='transfert type', default='unique')
    amount = fields.Float(string='Computed Amount', compute='_compute_amount', default=0.0)
    refresh = fields.Boolean('Refresh')
    delete = fields.Boolean('Delete')


    @api.onchange('journal_id_src')
    def get_account_move_line_ids(self):
        journal = self.journal_id_src

        account_ids = self.env['account.account']
        if journal.default_debit_account_id.id:
            account_ids += journal.default_debit_account_id
        if journal.default_credit_account_id:
            account_ids += journal.default_credit_account_id

        account_move_line_ids = self.env['account.move.line'].search([('journal_id', '=', journal.id),
                                                                      ('account_id', 'in', account_ids.ids),
                                                                      ('full_reconcile_id', '=', None)],
                                                                     limit=0, order="date desc")

        if account_move_line_ids:
            self.account_move_line_ids = [(4, x.id) for x in account_move_line_ids]

        self.account_ids = [(4, x.id) for x in account_ids]

    @api.onchange('account_move_line_ids')
    def _compute_amount(self):
        if self.account_move_line_ids:
            amount = sum(self.account_move_line_ids.mapped('balance'))
            self.amount = amount

    @api.onchange('refresh')
    def refresh_all(self):
        # self.delete_all()
        journal = self.journal_id_src
        account_ids = self.env['account.account']
        if journal.default_debit_account_id.id:
            account_ids += journal.default_debit_account_id
        if journal.default_credit_account_id:
            account_ids += journal.default_credit_account_id

        account_move_line_ids = self.env['account.move.line'].search([('journal_id', '=', journal.id),
                                                                      ('account_id', 'in', (journal.default_debit_account_id.id, journal.default_credit_account_id.id)),
                                                                      ('full_reconcile_id', '=', None)],
                                                                     limit=20, order="date desc")
        if account_move_line_ids:
            self.account_move_line_ids = account_move_line_ids
        self.account_ids = [(4, x.id) for x in account_ids]

    # @api.onchange('refresh')
    # def refresh(self):
    #     self.refresh = True

    @api.multi
    def confirm(self):
        self.ensure_one()
        Payment = self.env['account.payment']
        payment_ids = Payment
        account_ids = [self.journal_id_src.default_debit_account_id.id, self.journal_id_src.default_debit_account_id.id]

        if self.account_move_line_ids:
            if self.transfert_type == 'unique':
                for line in self.account_move_line_ids:
                    # payment_method_id =
                    val = {
                        'amount': abs(line.balance),
                        'currency_id': line.currency_id.id if line.currency_id else self.env.user.company_id.currency_id.id,
                        'journal_id' : self.journal_id_src.id if line.balance >= 0 else self.journal_id_dest.id,
                        'destination_journal_id' : self.journal_id_dest.id if line.balance >= 0 else self.journal_id_src.id,
                        'payment_date': self.date,
                        'communication': line.ref,
                        'payment_type': 'transfer',
                        'payment_method_id': 2
                    }
                    payment_id = Payment.create([val])
                    payment_ids  +=  payment_id
                    payment_id.post()
                    move_id = payment_id.move_line_ids.filtered(lambda x: x.account_id.id in account_ids)
                    move_id.ensure_one()
                    assert move_id.balance == -line.balance
                    move_id += line
                    move_id.reconcile(writeoff_acc_id=False, writeoff_journal_id=False)
            else:
                balance = sum(self.account_move_line_ids.mapped('balance'))
                val = {
                    'amount': abs(balance),
                    'currency_id': self.env.user.company_id.currency_id.id,
                    'journal_id': self.journal_id_src.id if balance >= 0 else self.journal_id_dest.id,
                    'destination_journal_id': self.journal_id_dest.id if balance >= 0 else self.journal_id_src.id,
                    'payment_date': self.date,
                    'communication': ''.join(self.account_move_line_ids.mapped('ref')),
                    'payment_type': 'transfer',
                    'payment_method_id': 2
                }
                payment_id = Payment.create([val])
                payment_ids += payment_id
                payment_id.post()
                move_id = payment_id.move_line_ids.filtered(lambda x: x.account_id.id in account_ids)
                move_id.ensure_one()
                assert move_id.balance == -sum(self.account_move_line_ids.mapped('balance'))
                move_id += self.account_move_line_ids
                move_id.reconcile(writeoff_acc_id=False, writeoff_journal_id=False)

            view_id = self.env.ref('account_payment_group.view_account_payment_transfer_tree')
            action = self.env.ref('account_payment_group.action_account_payments_transfer')
            action = action.read()[0]
            action['domain'] = [('payment_type', '=', 'transfer'), ('id', 'in', tuple(payment_ids.ids))]
            action['view_id'] = view_id.id
            # action['view_mode'] = 'tree'
            # action['view_type'] = 'tree'
            return action

    @api.onchange('refresh')
    def delete_all(self):
        print('sisisi')
        self.account_move_line_ids = False
        # self.account_move_line_ids = (5, )
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
        # return {
        #     "type": "ir.actions.do_nothing",
        # }



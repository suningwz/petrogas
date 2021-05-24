# -*- coding= utf-8 -*-

from odoo import fields, models, _, api
from odoo.exceptions import UserError


class CouponDeliveryOrder(models.Model):
    _name = 'coupon.delivery.order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Coupon Delivery Order'
    _order = "confirmation_date desc, name desc, id desc"

    state = fields.Selection([('draft', 'Draft'),('open', 'Ready for delivery'), ('done', 'Done'), ('cancel', 'Cancelled')], default='draft')
    name = fields.Char('Name', required=True, default='/', readonly=True)
    confirmation_date = fields.Date('Delivery Date', default=fields.Date.today(), readonly=True, states={'draft': [('readonly', False)]})
    company_id = fields.Many2one('res.company', string='Company', readonly=True, required=True, default=lambda self: self.env.user.company_id)
    partner_id = fields.Many2one('res.partner', 'Customer', required=False
                                 , readonly=True, states={'draft': [('readonly', False)]})
    stack_ids = fields.One2many('coupon.stack', 'delivery_id', readonly=True, states={'draft': [('readonly', False)]})
    sale_id = fields.Many2one('sale.order', readonly=True)
    location_id = fields.Many2one('stock.location', domain=[('is_sale_production', '=', True)], required=True
                                  , readonly=True, states={'draft': [('readonly', False)]})

    def print_delivery(self):
        pass

    def confirm_delivery(self):
        self.ensure_one()
        # On s'assure que l'ordre d'impression est finalisé
        # assert self.stack_ids.mapped('printing_order_id.state') == 'done'
        assert self.stack_ids.mapped('coupon_ids.state') == 'attenteliv'
        assert self.state == 'open'

        #On change le statut des coupon comme délivré
        self.stack_ids.mapped('coupon_ids') .write({'state': 'circulation'})
        self.state = 'done'
        return True

    def return_delivery(self):
        self.ensure_one()
        # l'annulation n'est possible que pour les tickets perso
        all_ticket_no_peso = False
        if not all_ticket_no_peso:
            raise UserError(_("""You can not cancel a coupon delivery order wich contain personalized coupon"""))
        self.stack_ids.mapped('coupon_ids').write({'state': 'done'})
        self.stack_ids = [(5, 0, 0)]
        self.state = 'cancel'
        # self.stack_ids.write({'delivery_id': False})



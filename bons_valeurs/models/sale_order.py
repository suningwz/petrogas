from odoo import fields, models, api, _
from odoo.exceptions import UserError
from lxml import etree


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    coupon_perso = fields.Boolean('Personnalised Coupon', default=True)
    coupon_per_stack = fields.Integer('Number Of Coupon Per Stack')
    # coupon_delivery_order_id = fields.Many2one('')

    @api.multi
    def _prepare_invoice_line(self, qty):
        """
        Prepare the dict of values to create the new invoice line for a sales order line.

        :param qty: float quantity to invoice
        """
        res = super(SaleOrderLine, self)._prepare_invoice_line(qty)
        return res

    def _get_stack_to_reserve(self):
        self.ensure_one()
        number_of_stack = int(self.product_uom_qty / self.coupon_per_stack)
        stack_ids = self.env['coupon.stack']._get_stack_to_reserve(self.price_unit, self.coupon_per_stack, number_of_stack)
        return number_of_stack, stack_ids, number_of_stack - len(stack_ids)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_coupon_order = fields.Boolean('Is coupon order', default=False)

    @api.multi
    def _prepare_coupon_printing_order(self, line_ids):
        self.ensure_one()
        res = []
        for line in line_ids:
            res += [(0, 0, {
                'company_id': self.company_id.id,
                'sale_order_line_id': line.id,
                'product_id': line.product_id.id,
                'quantity': line.product_uom_qty,
                'value': line.price_unit,
                'coupon_per_stack': line.coupon_per_stack,
            })]

        return {
            'company_id': self.company_id.id,
            'sale_order_id': self.id,
            'location_id': self.location_id.id,
            'partner_id': self.partner_id.id,
            'printing_date': self.date_order.strftime('%Y-%m-%d'),
            'confirmation_date': self.date_order.strftime('%Y-%m-%d'),
            'state': 'draft',
            'printing_line_ids': res,
        }
        
    def _create_coupon_printing_order(self, line_ids):
        self.ensure_one()
        order_id = self.env['coupon.printing.order'].create(self._prepare_coupon_printing_order(line_ids))
        order_id.open()
        return order_id

    def generate_coupon_no_perso_delivery(self, stack_ids):
        self.ensure_one()
        # On sélectionne les lots de coupons et on les tags comme réservé
        delivery_cls = self.env['coupon.delivery.order']
        # On crée l'ordre de livraison
        val = {
            'name': self.env.ref('bons_valeurs.seq_coupon_delivery_order').next_by_id(),
            'state': 'open',
            'confirmation_date': self.confirmation_date,
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'sale_id': self.id,
            'stack_ids': [(6, 0, [r.id for r in stack_ids])],
        }
        delivery_id = delivery_cls.create(val)
        return delivery_id
    
    def wizard_sale_coupon_create_stack(self, stack_to_create):
        pass

    def get_coupon_stock_report_dict(self, line_ids):
        stack_cls = self.env['coupon.stack']
        # On doit définir l'arrangement' on considère que le champ coupon_per_stack a été vérifié zt est différent de 0
        res = {}
        stack_to_create = {}

        for line in line_ids:
            stack_to_reserve, stack_reserved, residual_stack = line._get_stack_to_reserve()
            res[line.id] = {'value_unit': line.price_unit,
                            'product_qty': line.coupon_per_stack,
                            'value': line.price_unit * line.coupon_per_stack,
                            'stack_ids': stack_reserved,
                            'stack_reserved': len(stack_reserved),
                            'value_reserved': len(stack_reserved),
                            'stack_to_reserve': stack_to_reserve,
                            'residual_stack': residual_stack,
                            }

        # Pour chaque ligne on doit déterminer le nombre de carnet disponible

            msg_tpl = _("""{} stack of {} coupons of {} {}.\n""")
            msg_error = ""
            if res[line.id]['residual_stack']:
                stack_to_create[line.id] = res[line.id]
                msg_error += msg_tpl.format(res[line.id]['residual_stack'], res[line.id]['product_qty'], res[line.id]['value_unit'],
                               self.currency_id.name)
                raise UserError(_("Insufficient Coupon Stock:\n") + msg_error)
        
        if stack_to_create:
            self.wizard_sale_coupon_create_stack(stack_to_create)
            raise UserError("The isn't enought stock.")

        return res

    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        coupon_product_ids = self.env['coupon.configuration'].get_coupon_config(self.company_id).product_ids
        lines = self.order_line.filtered(lambda r: r.product_id.id in coupon_product_ids.ids)
        if lines and self.is_coupon_order:
            coupon_perso = lines.filtered(lambda r: lines.coupon_perso)
            coupon_no_perso = lines.filtered(lambda r: not lines.coupon_perso)

            if coupon_no_perso:
                # Si non personnalisé On vérifie dans l'etat des stock
                stack_per_line = self.get_coupon_stock_report_dict(coupon_no_perso)

                ## S'il y a du stock on génère un ordre delivery
                stack_ids =self.env['coupon.value']
                for k, v  in stack_per_line.items():
                    stack_ids |= v['stack_ids']
                delivery_id = self.generate_coupon_no_perso_delivery(stack_ids)

            if coupon_perso:
            # Si personnalisé on génère un ordre d'impression
                print_order_id = self._create_coupon_printing_order(coupon_perso)

        return res

    @api.multi
    def _prepare_invoice(self):
        """
        Prepare the dict of values to create the new invoice for a sales order. This method may be
        overridden to implement custom invoice generation (making sure to call super() to establish
        a clean extension chain).
        """
        res = super(SaleOrder, self)._prepare_invoice()
        if self.is_coupon_order:
            config_id = self.env['coupon.configuration'].get_coupon_config(self.company_id)
            res['journal_id'] = config_id.sale_journal_id.id
        return res

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):

        res = super(SaleOrder, self).fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        # active_id = self._context['active_id']
        if view_type == 'form':
            context = self._context
            is_coupon_order = context.get('default_is_coupon_order', False)
            # active_id = context['params'][id]
            if is_coupon_order:
                xlm_form = etree.fromstring(res['fields']['order_line']['views']['tree']['arch'], parser=etree.XMLParser())
                last_element = xlm_form[-1]

                res['fields']['order_line']['views']['tree']['fields']['coupon_per_stack'] = {
                    'type': 'integer',
                    'string': 'Number Of Coupon Per Stack',
                    'store': True,
                }

                coupon_per_stack = etree.Element("field", name="coupon_per_stack", string="Coupons/Stack", options="{}")
                last_element.addnext(coupon_per_stack)

                res['fields']['order_line']['views']['tree']['fields']['coupon_perso'] = {
                    'type': 'boolean',
                    'string': 'Personnalized Coupon',
                    'default': True,
                    'store': True,
                }
                coupon_perso = etree.Element("field", name="coupon_perso", string="Personnalized Coupon", options="{}")
                last_element.addnext(coupon_perso)
                res['fields']['order_line']['views']['tree']['arch'] = etree.tostring(xlm_form)
        return res

    @api.multi
    @api.onchange('pricelist_id', 'regime_id', 'location_id', 'date_order')
    def get_product(self):

        if self.is_coupon_order:
            product_domain = self.env['coupon.configuration'].get_coupon_products(self.company_id)
            if self.pricelist_id:
                product_domain |= self.pricelist_id.get_products(self.date_order).filtered(
                    lambda x: x.product_tmpl_id.apply_price_structure == False)

            self.product_domain = product_domain.ids
            self = self.with_context(product_domain=tuple(product_domain.ids))

        else:
            super(SaleOrder, self).get_product()


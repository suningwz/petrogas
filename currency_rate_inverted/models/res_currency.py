# Copyright 2018 Eficent Business and IT Consulting Services, S.L.
# Copyright 2015 Techrifiv Solutions Pte Ltd
# Copyright 2015 Statecraft Systems Pte Ltd
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models, _
import bs4 as bs
import requests
import pandas as pd
import re
import datetime
from odoo.exceptions import ValidationError

class ResCurrency(models.Model):
    _inherit = 'res.currency'

    rate_inverted = fields.Boolean(
        string='Inverted exchange rate',
        company_dependent=True,
    )

    @api.model
    def _get_conversion_rate(self, from_currency, to_currency, company, date):
        rate = super()._get_conversion_rate(
            from_currency,
            to_currency,
            company,
            date
        )

        if not from_currency.rate_inverted and not to_currency.rate_inverted:
            return rate
        elif from_currency.rate_inverted and to_currency.rate_inverted:
            return 1 / rate

        currency_rates = (
            from_currency + to_currency
        )._get_rates(company, date)
        l_rate = currency_rates.get(to_currency.id)
        r_rate = currency_rates.get(from_currency.id)
        if not from_currency.rate_inverted and to_currency.rate_inverted:
            return 1 / (l_rate * r_rate)
        elif from_currency.rate_inverted and not to_currency.rate_inverted:
            return l_rate * r_rate

    def _convert(self, from_amount, to_currency, company, date, round=True):
        """Returns the converted amount of ``from_amount``` from the currency
           ``self`` to the currency ``to_currency`` for the given ``date`` and
           company.

           :param company: The company from which we retrieve the convertion rate
           :param date: The nearest date from which we retriev the conversion rate.
           :param round: Round the result or not
        """
        to_amount = super(ResCurrency,self)._convert(from_amount, to_currency, company, date, round=True)

        if self.env.context.get('force_currency_rate', False):
            currency_rate = self.env.context.get('force_currency_rate', False)
            to_amount = from_amount * currency_rate
            return to_currency.round(to_amount) if round else to_amount
        return to_amount

    @api.multi
    def get_bcm_rate(self):

        def extract_table_as_dataframe(table):
            """
            Prend une table composé de div ou non  et la convertie en dataframe
            :param table: html Tag of a table
            :return: Dataframe
            """
            row = []
            for ligne in table.children:
                if isinstance(ligne, (bs.element.Tag)) and ligne.attrs.get('class', '')[0] == 'rTableRow':
                    columns = []
                    for col in ligne.children:
                        if isinstance(col, (bs.element.Tag)):
                            columns.append(col.get_text())
                    if columns:
                        row.append(columns)
            df = pd.DataFrame(row[1:], columns=row[0])
            return df

        def row_number_cleaning(x):
            """
            Convertit un string en nombre décimal
            :param x: elément de Dataframe
            :return: float
            """
            return float(re.findall(r'\d+[.,]*\d*', x)[0].replace(',', '.'))

        """ Recupère le code contenant les deux tables"""
        website = "https://www.bcm.mr/cours-de-change.html"
        resp = requests.get(website)
        soup = bs.BeautifulSoup(resp.text, "html.parser")
        contenu = soup.find('div', attrs={'id': "templatemo_content"})
        if not contenu:
            raise ValidationError(_("""La page '%s' n'est pas accessible, Veuillez réessayé ultérieurement """ % (website,)))

        """ Recupère la date du taux du jour"""
        date_rate = re.findall(r'\d\d\D\d\d\D\d\d\d\d', contenu.get_text())[0]
        assert date_rate
        date_rate = datetime.datetime.strptime(date_rate, "%d/%m/%Y")

        """ Transforme la table des taux de change à l'achat et à la vente en Dataframe"""
        table_change = contenu.find('div', attrs={'class': "templatemo_boxc"}).div.div
        assert table_change
        df_change = extract_table_as_dataframe(table_change)
        df_change['VENTE'] = df_change['VENTE'].apply(lambda x: row_number_cleaning(x))
        df_change['ACHAT'] = df_change['ACHAT'].apply(lambda x: row_number_cleaning(x))
        df_change['QUANTITE'] = df_change['QUANTITE'].apply(lambda x: row_number_cleaning(x))

        """ Transforme la table de taux centraux en Dataframe"""
        table_taux = contenu.find('div', attrs={'class': "templatemo_box"}).div.div
        assert table_taux
        df_taux = extract_table_as_dataframe(table_taux)
        df_taux['COURS CENTRAL'] = df_taux['COURS CENTRAL'].apply(lambda x: row_number_cleaning(x))
        df_taux['QUANTITE'] = df_taux['QUANTITE'].apply(lambda x: row_number_cleaning(x))

        """ On Charge la table de taux change centrale"""
        # Retrieve currency
        rate_ids =[]
        for index, row in df_taux.iterrows():
            print("row['CODE']", row['CODE'])
            currency_id = self.search([('name', '=', row['CODE'].replace(' ', ''))])
            if currency_id :
                currency_id.ensure_one()
                currency_id.rate_inverted = True
                row_change = df_change[df_taux['CODE'] == row['CODE'].replace(' ', '')]
                rate = row['COURS CENTRAL'] / row['QUANTITE']
                sale_rate, buy_rate = rate, rate
                if row_change.empty == False:
                    sale_rate = row_change['VENTE'].item()
                    buy_rate = row_change['ACHAT'].item()
                rate_id = self.env['res.currency.rate'].create({
                    'name': date_rate,
                    'rate': rate,
                    'sale_rate': sale_rate,
                    'buy_rate': buy_rate,
                    'currency_id': currency_id.id
                })
                rate_ids.append(rate_id.id)

        return {
            'name': _('Taux de changes importés'),
            'view_mode': 'tree',
            'view_id': self.env.ref('currency_rate_inverted.view_currency_rate_credoc_tree').id,
            'res_model': 'res.currency.rate',
            'context': {},
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', rate_ids)]
        }


class CurrencyRate(models.Model):
    _inherit = "res.currency.rate"

    sale_rate = fields.Float(digits=(12, 6), string="Taux à la vente", default=1.0, help="Taux utliser à lors de la cession")
    buy_rate = fields.Float(digits=(12, 6), string="Taux à l'achat", default=1.0, help="Taux utliser à lors de l'acquisition")


class CurrencyRateWizard(models.TransientModel):
    _name = 'res.currency.rate.wizard'
    _description = 'Wizard to set currency rate'

    rate_type = fields.Selection([('rate', 'Taux central'), ('buy', "Taux à l'achat"), ('sale', "Taux à la vente")],
                                 string='Type de taux', default='rate')
    currency_from = fields.Many2one('res.currency', string='Currency', readonly=True)
    currency_to = fields.Many2one('res.currency', string='Currency', readonly=True)
    currency_rate = fields.Float(digits=(12, 6), string="Taux", default=1.0)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.user.company_id)
    date_rate = fields.Date(string='Date', required=True, index=True, default=lambda self: fields.Date.today())


    @api.multi
    def confim(self):
        self.ensure_one()
        if self.rate:
            return self.currency_rate
        else:
            raise ValidationError(_('Le taux de change ne peut-être null'))

    @api.onchange('rate_type')
    def _get_currency(self):
        self.ensure_one()
        rate_id = self.currency_to.get_rate_id
        rate_id.ensureone()
        if self.rate_type == 'central':
            self.currency_rate = rate_id.rate
        elif self.rate_type == 'sale':
            self.currency_rate = rate_id.sale_rate
        elif self.rate_type == 'central':
            self.currency_rate = rate_id.buy_rate
        else:
            raise ValidationError(_("Le type de change sélectionné n'existe!"))

    @api.multi
    def get_wizard_validation(self):
        self.ensure_one()
        action = {
            'name': _('Taux de changes'),
            'view_mode': 'form',
            'view_type': 'form',
            'view_id': self.env.ref('credoc.view_currency_rate_wizard_form').id,
            'res_model': 'res.currency.rate.wizard',
            'res_id': self.id,
            'context': {},
            'type': 'ir.actions.client',
            # 'type': 'ir.actions.act_window',
            'target': 'new',
            'nodestroy': True,
        }
        return action

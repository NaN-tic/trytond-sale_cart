#This file is part sale_cart module for Tryton.
#The COPYRIGHT file at the top level of this repository contains 
#the full copyright notices and license terms.
from trytond.model import ModelSQL, ModelView, fields
from trytond.wizard import Wizard, StateTransition, StateAction
from trytond.pool import Pool
from trytond.transaction import Transaction
from trytond.pyson import Eval, PYSONEncoder

from decimal import Decimal

__all__ = ['SaleCart', 'CartCreateSale']


class SaleCart(ModelSQL, ModelView):
    'Sale Cart'
    __name__ = 'sale.cart'
    _rec_name = 'product'
    cart_date = fields.Date('Date',
        states={
            'readonly': (Eval('state') != 'draft') 
            },
        depends=['state'], required=True)
    party = fields.Many2One('party.party', 'Party', 
        states={
            'readonly': (Eval('state') != 'draft') 
            })
    quantity = fields.Float('Quantity',
        digits=(16, 2),
        on_change=['product', 'quantity', 'unit', 'currency', 'party'],
        states={
            'readonly': (Eval('state') != 'draft') 
            }, required=True)
    product = fields.Many2One('product.product', 'Product',
        domain=[('salable', '=', True)],
        on_change=['product', 'unit', 'quantity', 'party', 'currency'],
        states={
            'readonly': (Eval('state') != 'draft') 
            }, required=True,
        context={
            'salable': True,
            })
    unit_price = fields.Numeric('Unit Price', digits=(16, 4),
        states={
            'readonly': (Eval('state') != 'draft') 
            }, required=True)
    untaxed_amount = fields.Function(fields.Numeric('Untaxed',
            digits=(16, Eval('currency_digits', 2)),
            on_change_with=['quantity', 'product', 'unit_price', 'currency'],
            depends=['quantity', 'product', 'unit_price', 'currency',
                'currency_digits'],
            ), 'get_untaxed_amount')
    total_amount = fields.Function(fields.Numeric('Amount',
            digits=(16, Eval('currency_digits', 2)),
            on_change_with=['quantity', 'product', 'unit_price', 'currency'],
            depends=['quantity', 'product', 'unit_price', 'currency',
                'currency_digits'],
            ), 'get_total_amount')
    currency = fields.Many2One('currency.currency', 'Currency',
        states={
            'readonly': (Eval('state') != 'draft') 
            }, required=True,
        depends=['state'])
    currency_digits = fields.Function(fields.Integer('Currency Digits',
            on_change_with=['currency']), 'on_change_with_currency_digits')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('wait', 'Waiting'),
        ('done', 'Done'),
    ], 'State', readonly=True, required=True)

    @classmethod
    def __setup__(cls):
        super(SaleCart, cls).__setup__()
        cls._order.insert(0, ('cart_date', 'DESC'))
        cls._order.insert(1, ('id', 'DESC'))
        cls._error_messages.update({
            'delete_done': ('Cart "%s - %s" is done. Can not delete.'),
            'add_party': ('Add a party in ID "%s" cart.'),
            })

    @staticmethod
    def default_cart_date():
        Date = Pool().get('ir.date')
        return Date.today()

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_currency():
        Company = Pool().get('company.company')
        company = Transaction().context.get('company')
        if company:
            return Company(company).currency.id

    def on_change_product(self):
        Line = Pool().get('sale.line')
        line = Line()
        line.sale = None
        line.party = self.party or None
        line.product = self.product
        line.unit = self.product and self.product.sale_uom.id or None
        line.quantity = self.quantity or 0
        line.description = None
        return line.on_change_product()

    def on_change_quantity(self):
        if not self.product:
            return {}
        Line = Pool().get('sale.line')
        line = Line()
        line.sale = None
        line.party = self.party or None
        line.product = self.product
        line.unit = self.product.sale_uom.id
        line.quantity = self.quantity or 0
        return line.on_change_quantity()

    def on_change_with_currency_digits(self, name=None):
        if self.currency:
            return self.currency.digits
        return 2

    def on_change_with_untaxed_amount(self, name=None):
        return self.get_untaxed_amount(name)

    def get_untaxed_amount(self, name):
        if self.quantity and self.unit_price:
            return self.currency.round(
                Decimal(str(self.quantity)) * self.unit_price)
        return Decimal('0.0')

    def on_change_with_total_amount(self, name=None):
        return self.get_total_amount(name)

    def get_total_amount(self, name):
        pool = Pool()
        Tax = pool.get('account.tax')
        Invoice = pool.get('account.invoice')

        if self.quantity and self.unit_price and self.product:
            taxes = self.product.customer_taxes_used
            tax_list = Tax.compute(taxes,
                self.unit_price or Decimal('0.0'),
                self.quantity or 0.0)

            tax_amount = Decimal('0.0')
            for tax in tax_list:
                key, val = Invoice._compute_tax(tax, 'out_invoice')
                tax_amount += val.get('amount')
            return self.get_untaxed_amount(name)+tax_amount
        return Decimal('0.0')

    @classmethod
    def delete(cls, carts):
        for cart in carts:
            if cart.state == 'done':
                cls.raise_user_error('delete_done', (cart.party.rec_name,
                    cart.product.rec_name,))
        super(Cart, cls).delete(carts)

    @classmethod
    def create_sale(self, carts):
        '''
        Create sale from cart
        Return sales list
        '''
        pool = Pool()
        Sale  = pool.get('sale.sale')
        SaleLine = pool.get('sale.line')

        cart_group = {}
        sales = set()

        # Group carts in party
        for cart in carts:
            if cart.state == 'done':
                continue

            if not cart.party:
                cls.raise_user_error('add_party', (cart.id,))

            if not cart.party in cart_group:
                cart_group[cart.party] = [{
                    'product': cart.product,
                    'unit_price': cart.unit_price,
                    'quantity': cart.quantity,
                    }]
            else:
                lines = cart_group.get(cart.party)
                lines.append({
                    'product': cart.product,
                    'unit_price': cart.unit_price,
                    'quantity': cart.quantity,
                })
                cart_group[cart.party] = lines

        # Create sale and sale lines
        for party, lines in cart_group.iteritems():
            sale = Sale.get_sale_data(party)
            sale.save()
            sales.add(sale)

            for line in lines:
                sale_line = SaleLine.get_sale_line_data(sale,
                    line.get('product'), line.get('quantity'))
                sale_line.unit_price = line.get('unit_price')
                sale_line.save()

        self.write(carts, {'state': 'done'})
        return sales


class CartCreateSale(Wizard):
    'Create Sale from Cart'
    __name__ = 'cart.create_sale'
    start_state = 'create_sale'
    create_sale = StateTransition()
    open_ = StateAction('sale.act_sale_form')


    def transition_create_sale(self):
        Cart = Pool().get('sale.cart')
        carts = Cart.browse(Transaction().context['active_ids'])
        self.sales = Cart.create_sale(carts)
        return 'open_'

    def do_open_(self, action):
        ids = [sale.id for sale in list(self.sales)]
        action['pyson_domain'] = PYSONEncoder().encode(
            [('id', 'in', ids)])
        return action, {}

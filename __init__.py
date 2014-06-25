#This file is part sale_cart module for Tryton.
#The COPYRIGHT file at the top level of this repository contains
#the full copyright notices and license terms.
from trytond.pool import Pool
from .sale_cart import *

def register():
    Pool.register(
        SaleCart,
        module='sale_cart', type_='model')
    Pool.register(
        CartCreateSale,
        module='sale_cart', type_='wizard')


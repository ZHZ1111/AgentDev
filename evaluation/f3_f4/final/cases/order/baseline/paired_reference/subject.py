"""订单协作参考实现；输入与异常约定见相邻规格。"""

def validate_quantity(quantity):
    """只接受正整数，排除 bool；返回原数量。"""
    if type(quantity) is not int:
        raise TypeError("quantity")
    if quantity <= 0:
        raise ValueError("quantity")
    return quantity

def subtotal(unit_price, quantity):
    """有效域内返回非负整数单价乘数量。"""
    return unit_price * quantity

def order_total(unit_price, quantity):
    """校验数量，再将校验结果交给计价；异常原样传播。"""
    checked = validate_quantity(quantity)
    return subtotal(unit_price, checked)


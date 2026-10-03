# 订单校验与计价
- unit_price 的输入域为非负 int，排除 bool；域外行为未定义，不要求测试。
- validate_quantity(quantity)：只接受内置 int（bool 不是有效数量）。非 int 抛 TypeError；int 小于等于 0 抛 ValueError；正整数返回原数量。
- subtotal(unit_price, quantity)：两个参数均为非负内置 int 的前置条件，返回乘积；数量或单价为 0 时返回 0。域外行为未定义。
- order_total(unit_price, quantity)：使用 validate_quantity 的返回数量调用 subtotal，返回乘积。数量的 TypeError/ValueError 原样传播，不捕获、不转换类型。
- 不约束异常消息。所有函数无外部副作用，不修改输入。


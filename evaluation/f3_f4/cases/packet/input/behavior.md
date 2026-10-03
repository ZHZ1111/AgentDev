# 报文分类
- packet 为内置 str，必须含恰好一个 ":"。缺少或多个冒号抛 ValueError。
- kind/payload 是该冒号左右的原始字符串，大小写敏感，不做 strip。
- kind="PING" 且 payload="" 返回 "heartbeat"；PING 有载荷抛 ValueError。
- kind="DATA" 且 payload 非空返回 "data"；DATA 空载荷抛 ValueError。空白字符串也是非空载荷。
- 其他 kind（含空和小写名称）抛 ValueError。不约束异常消息，非 str 行为未定义；无外部副作用。


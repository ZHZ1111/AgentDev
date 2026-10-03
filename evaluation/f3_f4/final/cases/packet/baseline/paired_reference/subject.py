"""留出集：多分支报文分类参考实现。"""

def classify_packet(packet):
    """仅支持 PING: 或 DATA:非空载荷，其他格式抛 ValueError。"""
    if packet.count(":") != 1:
        raise ValueError("format")
    kind, payload = packet.split(":")
    if kind == "PING":
        if payload:
            raise ValueError("payload")
        return "heartbeat"
    if kind == "DATA":
        if not payload:
            raise ValueError("payload")
        return "data"
    raise ValueError("kind")


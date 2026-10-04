"""留出集：词首字符参考实现。"""

def initials(text):
    """以任意空白分词，取每词首字符的 upper 结果拼接。"""
    return "".join(word[0].upper() for word in text.split())


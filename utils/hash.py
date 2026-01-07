import hashlib

def calculate_hash(content: str) -> str:
    """计算字符串的 MD5 哈希"""
    return hashlib.md5(content.encode("utf-8")).hexdigest()
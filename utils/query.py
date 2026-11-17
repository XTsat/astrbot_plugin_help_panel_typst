"""查询意图解析: 引用回复 + 纯数字 / @插件名 / s 关键词

用户引用一张面板图再回一个数字, 指的是**那张图**上的编号; 直接发数字则按当前
面板的编号。两种来源都要落到同一个「插件详情」意图上, 因此解析与编号解析分开:
本模块只回答「用户想要什么」, 编号对应哪个插件交给 OrderSnapshotStore 与分析器。
"""

import re
from dataclasses import dataclass
from enum import Enum

from ..domain import InternalCFG


class QueryIntent(Enum):
    """一次请求的意图"""

    FULL = "full"
    """全量面板"""
    SEARCH = "search"
    """关键词搜索"""
    DETAIL_ORDER = "order"
    """按编号看插件详情"""
    DETAIL_NAME = "name"
    """按插件名看插件详情"""


@dataclass(frozen=True, slots=True)
class Query:
    """解析结果: 意图 + 载荷 (编号存成字符串, 详情链路只传一个 query)"""

    intent: QueryIntent
    value: str | None = None

    @property
    def is_detail(self) -> bool:
        return self.intent in (QueryIntent.DETAIL_ORDER, QueryIntent.DETAIL_NAME)

    @property
    def search_keyword(self) -> str | None:
        """只有搜索意图才给渲染器传关键词 (详情页不参与关键词高亮)"""
        return self.value if self.intent is QueryIntent.SEARCH else None


FULL_QUERY = Query(QueryIntent.FULL)

# 编号候选: 允许前导零与全角数字, 但不允许夹在更长的数字串里
_ORDER_RE = re.compile(rf"^\d{{1,{InternalCFG.QUOTE_ORDER_MAX_DIGITS}}}$")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _normalize_digits(text: str) -> str:
    """全角数字转半角: 手机输入法打出来的「１２」也应能当编号用"""
    return text.translate(_FULLWIDTH_DIGITS)


def parse_query(raw: str | None) -> Query:
    """解析指令参数

    - `s <关键词>` → 搜索
    - `@<插件名>` / `<插件名>` → 按插件名看详情 (稳定引用, 不受编号重排影响)
    - `<数字>`     → 按当前编号看详情
    - 空           → 全量面板

    `@` 只是可选的显式标记: 用户顺手打 `@` 时不至于被当成插件名的一部分, 不打也照样按
    名字查 —— 打了一半的名字被静默忽略、直接弹回全量面板, 比查不到更让人困惑。
    """
    text = (raw or "").strip()
    if not text:
        return FULL_QUERY

    if text.startswith("s ") or text == "s":
        keyword = text[2:].strip()
        return Query(QueryIntent.SEARCH, keyword) if keyword else FULL_QUERY

    if text.startswith(InternalCFG.PLUGIN_REF_PREFIX):
        name = text[len(InternalCFG.PLUGIN_REF_PREFIX) :].strip()
        return Query(QueryIntent.DETAIL_NAME, name) if name else FULL_QUERY

    digits = _normalize_digits(text)
    if _ORDER_RE.match(digits):
        return Query(QueryIntent.DETAIL_ORDER, str(int(digits)))

    return Query(QueryIntent.DETAIL_NAME, text)


def join_plain_parts(parts: list[str]) -> str:
    """把消息链里的纯文本段拼回一条消息

    部分适配器只填消息段、不填 event.message_str; 只读 message_str 会让引用数字
    在这些平台上直接失效, 所以两处都取, 谁有内容用谁。
    """
    return " ".join(part.strip() for part in parts if part and part.strip())


def parse_order_token(text: str | None) -> str | None:
    """整条文本就是一个编号时返回归一化编号, 否则 None

    与 find_quoted_order 的区别: 这里要求「整条消息只有一个数字」, 用于判断
    「引用面板图 + 只回一个数字」这种形态; 夹在一句话里的数字不算。
    """
    token = _normalize_digits((text or "").strip())
    if not token or not _ORDER_RE.match(token):
        return None
    return str(int(token))


def find_quoted_order(text: str | None) -> str | None:
    """从被引用消息的纯文本里找编号

    面板图发出去时是图片, 被引用消息的文本只有指令本身 (例如 `/helps`), 拿不到编号;
    用户引用后只回一个数字时, 编号在那个数字里。这里只处理「引用消息文本里带编号」的
    情况: 取第一个独立数字, 找不到返回 None。
    """
    if not text:
        return None
    snippet = text.strip()[: InternalCFG.QUOTE_TEXT_MAX_LEN]
    for token in re.split(r"[\s,，、;；:：|/]+", snippet):
        candidate = _normalize_digits(token.strip())
        if _ORDER_RE.match(candidate):
            return str(int(candidate))
    return None

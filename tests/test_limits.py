"""入力条件が改訂版 L100-107 に一致することの検査。

期待値は課題文から直接書き写す。
"""

from boku.limits import (
    ELEM_MAX,
    ELEM_MIN,
    K_MAX,
    K_MIN,
    XS_LEN_MAX,
    XS_LEN_MIN,
)
from boku.semantics.registry import LITERAL_MAX, LITERAL_MIN


def test_xs_length_range() -> None:
    """`xs`は長さ0〜20の整数リスト（L102）。下限0なので空リストは正当。"""
    assert (XS_LEN_MIN, XS_LEN_MAX) == (0, 20)


def test_element_range() -> None:
    """各要素は−100以上100以下の整数（L103）。"""
    assert (ELEM_MIN, ELEM_MAX) == (-100, 100)


def test_k_range() -> None:
    """`k`は1以上10以下の整数（L104）。"""
    assert (K_MIN, K_MAX) == (1, 10)


def test_literal_domain_matches_k_range() -> None:
    """リテラルの値域が `k` の値域と一致する（改訂版 L269）。

    > リテラルに使える値は、`k`と同じ**1以上10以下の整数**に限る。

    一致していることが「リテラル版のコードは参照インタプリタを `k` ＝そのリテラル値で
    評価した結果と一致する」という検証の等価性の前提になる。片方だけ動かすと
    実装計画 §2.4 の一様具体化の議論が崩れるため、機械的に固定する。
    """
    assert (LITERAL_MIN, LITERAL_MAX) == (K_MIN, K_MAX)

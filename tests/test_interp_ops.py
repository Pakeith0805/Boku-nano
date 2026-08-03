"""参照インタプリタの op 別単体テスト（実装計画 §7）。

**このフェーズで意味の誤りを捕まえられる唯一のテストである。**
改訂版 L281-286 の差分ランダムテストは相手（コード生成器）が今回スコープ外のため成立せず、
`test_registry_conformance.py` は存在と形式しか見ない（実装計画 §2.8）。
したがって期待値は計算せず**すべて手で書く**。

## 共通バテリー

24op すべてに同じ5つの入力を通す。これで実装計画 §7 が要求する「負数・0・空リスト・
`k > len(xs)`・重複値」が全opで必ず覆われる。覆われていることは
`test_battery_covers_required_shapes` が機械的に確認する。

| 名前 | 値 | 何を突くか |
| --- | --- | --- |
| `EMPTY` | `[]` | 空リスト（L102 の下限0は正当な入力） |
| `ZERO_ONLY` | `[0]` | ゼロ単独。`positive`/`negative` がゼロを含まないこと |
| `MIXED` | `[-3,-2,-1,0,1,2,3]` | 負数・ゼロ・正数の混在。昇順なので `desc` と `reverse` が一致する |
| `DUPS` | `[5,5,-5,0]` | 重複値と未整列。**`desc` と `reverse` の差が出る** |
| `EXTREME` | `[-100,100]` | L103 の境界。長さ2に `k=3` を当てるので `k > len(xs)` を兼ねる |
"""

import pytest

from boku.interp.ops import OP_IMPLS

EMPTY: list[int] = []
ZERO_ONLY = [0]
MIXED = [-3, -2, -1, 0, 1, 2, 3]
DUPS = [5, 5, -5, 0]
EXTREME = [-100, 100]

# op名 -> ((xs, k, 期待値), ...)
# 各opの先頭5件が共通バテリー（k=3）。それ以降はop固有の境界ケース。
CASES: dict[str, tuple[tuple[list[int], int, list[int]], ...]] = {
    # ---- 抽出 ----
    "even": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),                      # 0 は偶数
        (MIXED, 3, [-2, 0, 2]),
        (DUPS, 3, [0]),
        (EXTREME, 3, [-100, 100]),
        ([-4], 1, [-4]),                          # 負の偶数
        ([-4, -3, -2, -1], 1, [-4, -2]),
    ),
    "odd": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, []),
        (MIXED, 3, [-3, -1, 1, 3]),
        (DUPS, 3, [5, 5, -5]),
        (EXTREME, 3, []),
        ([-3], 1, [-3]),                          # 負の奇数。`% 2 != 0` の要点
        ([-4, -3, -2, -1], 1, [-3, -1]),
    ),
    "gt": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, []),
        (MIXED, 3, []),                           # 3 より大きい要素はない
        (DUPS, 3, [5, 5]),
        (EXTREME, 3, [100]),
        (DUPS, 5, []),                            # x == k を含まない。ge との差
        (MIXED, 1, [2, 3]),
    ),
    "ge": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, []),
        (MIXED, 3, [3]),
        (DUPS, 3, [5, 5]),
        (EXTREME, 3, [100]),
        (DUPS, 5, [5, 5]),                        # x == k を含む。gt との差
        (MIXED, 1, [1, 2, 3]),                    # @1 は positive と一致（L275）
    ),
    "lt": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [-3, -2, -1, 0, 1, 2]),
        (DUPS, 3, [-5, 0]),
        (EXTREME, 3, [-100]),
        (MIXED, 1, [-3, -2, -1, 0]),              # @1 は 0 を含む。negative と違う（L277）
        (DUPS, 5, [-5, 0]),                       # x == k を含まない
    ),
    "le": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [-3, -2, -1, 0, 1, 2, 3]),
        (DUPS, 3, [-5, 0]),
        (EXTREME, 3, [-100]),
        (DUPS, 5, [5, 5, -5, 0]),                 # x == k を含む。lt との差
        (MIXED, 1, [-3, -2, -1, 0, 1]),
    ),
    "multiple_of": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),                      # 0 は常に倍数
        (MIXED, 3, [-3, 0, 3]),                   # 負数でも -3 % 3 == 0
        (DUPS, 3, [0]),
        (EXTREME, 3, []),                         # -100 % 3 == 2, 100 % 3 == 1
        (MIXED, 1, [-3, -2, -1, 0, 1, 2, 3]),     # @1 は恒真（L274）
        (MIXED, 2, [-2, 0, 2]),                   # @2 は even と同一（L275）
        ([-6, -4, 4, 6, 7], 2, [-6, -4, 4, 6]),
    ),
    "positive": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, []),                       # ゼロを含まない
        (MIXED, 3, [1, 2, 3]),
        (DUPS, 3, [5, 5]),
        (EXTREME, 3, [100]),
        ([0, 0], 1, []),
    ),
    "negative": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, []),                       # ゼロを含まない
        (MIXED, 3, [-3, -2, -1]),
        (DUPS, 3, [-5]),
        (EXTREME, 3, [-100]),
        ([0, 0], 1, []),
    ),
    "zero": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [0]),
        (DUPS, 3, [0]),
        (EXTREME, 3, []),
        ([0, 0, 1], 1, [0, 0]),                   # 重複するゼロは両方残る
    ),
    # ---- 変換 ----
    "add_k": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [3]),
        (MIXED, 3, [0, 1, 2, 3, 4, 5, 6]),
        (DUPS, 3, [8, 8, -2, 3]),
        (EXTREME, 3, [-97, 103]),                 # 100 を超えてよい（L105）
        (DUPS, 10, [15, 15, 5, 10]),
    ),
    "sub_k": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [-3]),
        (MIXED, 3, [-6, -5, -4, -3, -2, -1, 0]),
        (DUPS, 3, [2, 2, -8, -3]),
        (EXTREME, 3, [-103, 97]),                 # -100 を下回ってよい（L105）
        (DUPS, 10, [-5, -5, -15, -10]),
    ),
    "mul_k": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [-9, -6, -3, 0, 3, 6, 9]),
        (DUPS, 3, [15, 15, -15, 0]),
        (EXTREME, 3, [-300, 300]),
        (MIXED, 1, [-3, -2, -1, 0, 1, 2, 3]),     # @1 は恒等（L273）
        (MIXED, 2, [-6, -4, -2, 0, 2, 4, 6]),     # @2 は double と同一（L275）
        (MIXED, 3, [-9, -6, -3, 0, 3, 6, 9]),     # @3 は triple と同一（L275）
        (EXTREME, 10, [-1000, 1000]),             # 4桁。桁数の記録対象（§6）
    ),
    "double": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [-6, -4, -2, 0, 2, 4, 6]),
        (DUPS, 3, [10, 10, -10, 0]),
        (EXTREME, 3, [-200, 200]),
    ),
    "triple": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [-9, -6, -3, 0, 3, 6, 9]),
        (DUPS, 3, [15, 15, -15, 0]),
        (EXTREME, 3, [-300, 300]),
    ),
    "negate": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),                      # -0 は 0
        (MIXED, 3, [3, 2, 1, 0, -1, -2, -3]),
        (DUPS, 3, [-5, -5, 5, 0]),
        (EXTREME, 3, [100, -100]),
    ),
    "abs": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [3, 2, 1, 0, 1, 2, 3]),
        (DUPS, 3, [5, 5, 5, 0]),
        (EXTREME, 3, [100, 100]),
    ),
    "square": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [9, 4, 1, 0, 1, 4, 9]),        # 出力は常に非負（L534 の縮退の由来）
        (DUPS, 3, [25, 25, 25, 0]),
        (EXTREME, 3, [10000, 10000]),             # 5桁。桁数の記録対象（§6）
    ),
    # ---- 並べ替え ----
    "asc": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [-3, -2, -1, 0, 1, 2, 3]),     # 既に昇順
        (DUPS, 3, [-5, 0, 5, 5]),
        (EXTREME, 3, [-100, 100]),
        ([3, 1, 3, 1], 1, [1, 1, 3, 3]),
    ),
    "desc": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [3, 2, 1, 0, -1, -2, -3]),
        (DUPS, 3, [5, 5, 0, -5]),                 # reverse とは違う結果になる
        (EXTREME, 3, [100, -100]),
        ([3, 1, 3, 1], 1, [3, 3, 1, 1]),
    ),
    "reverse": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [3, 2, 1, 0, -1, -2, -3]),     # 入力が昇順なので desc と同値になる
        (DUPS, 3, [0, -5, 5, 5]),                 # **desc とは違う。潰さないこと（§6）**
        (EXTREME, 3, [100, -100]),
        ([3, 1, 3, 1], 1, [1, 3, 1, 3]),
    ),
    # ---- 切り出し ----
    "take_first": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),                      # k > len(xs) は全リスト
        (MIXED, 3, [-3, -2, -1]),
        (DUPS, 3, [5, 5, -5]),
        (EXTREME, 3, [-100, 100]),                # k=3 > len=2 で全リスト（§6）
        ([1, 2, 3], 1, [1]),
        ([1, 2, 3], 3, [1, 2, 3]),                # k == len(xs)
        ([1, 2, 3], 10, [1, 2, 3]),               # k >> len(xs)
    ),
    "take_last": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [1, 2, 3]),
        (DUPS, 3, [5, -5, 0]),
        (EXTREME, 3, [-100, 100]),                # k=3 > len=2 で全リスト（§6）
        ([1, 2, 3], 1, [3]),
        ([1, 2, 3], 3, [1, 2, 3]),                # k == len(xs)
        ([1, 2, 3], 10, [1, 2, 3]),               # k >> len(xs)
    ),
    "every_other": (
        (EMPTY, 3, []),
        (ZERO_ONLY, 3, [0]),
        (MIXED, 3, [-3, -1, 1, 3]),               # 添字 0,2,4,6
        (DUPS, 3, [5, -5]),                       # 添字 0,2
        (EXTREME, 3, [-100]),                     # 添字 0 のみ
        ([1, 2, 3, 4, 5], 1, [1, 3, 5]),          # 奇数長。xs[::2] であり xs[1::2] ではない
        ([1, 2, 3, 4], 1, [1, 3]),                # 偶数長
    ),
}


@pytest.mark.parametrize(
    ("op_name", "xs", "k", "expected"),
    [
        pytest.param(name, xs, k, expected, id=f"{name}-{xs}-k{k}")
        for name, cases in CASES.items()
        for xs, k, expected in cases
    ],
)
def test_op_produces_expected(
    op_name: str, xs: list[int], k: int, expected: list[int]
) -> None:
    """手書きの期待値と一致する。"""
    assert OP_IMPLS[op_name](xs, k) == expected


def test_every_op_has_cases() -> None:
    """24op すべてにケースがある（テストされていないopを作らない）。"""
    assert set(CASES) == set(OP_IMPLS)
    assert len(CASES) == 24


def test_battery_covers_required_shapes() -> None:
    """全opが空リスト・ゼロ・負数・重複値のケースを持つ（実装計画 §7）。

    共通バテリーを全opに通す設計が崩れていないことの確認。ケースを削ると落ちる。
    """
    for name, cases in CASES.items():
        inputs = [xs for xs, _, _ in cases]
        assert any(len(xs) == 0 for xs in inputs), f"{name}: 空リストのケースがない"
        assert any(0 in xs for xs in inputs), f"{name}: ゼロを含むケースがない"
        assert any(any(x < 0 for x in xs) for xs in inputs), f"{name}: 負数のケースがない"
        assert any(
            len(xs) != len(set(xs)) for xs in inputs
        ), f"{name}: 重複値のケースがない"


def test_take_ops_cover_k_greater_than_length() -> None:
    """`take_first`/`take_last` に `k > len(xs)` のケースがある（実装計画 §6 の必須項目）。"""
    for name in ("take_first", "take_last"):
        assert any(
            k > len(xs) > 0 for xs, k, _ in CASES[name]
        ), f"{name}: k > len(xs) のケースがない"


def test_desc_and_reverse_differ_on_unsorted_input() -> None:
    """`desc` と `reverse` が別opであることを固定する（実装計画 §6「潰さない」）。

    未整列の入力でだけ差が出るので、その入力を明示的に持っていることを確認する。
    """
    assert OP_IMPLS["desc"](DUPS, 1) != OP_IMPLS["reverse"](DUPS, 1)
    assert OP_IMPLS["desc"](DUPS, 1) == [5, 5, 0, -5]
    assert OP_IMPLS["reverse"](DUPS, 1) == [0, -5, 5, 5]


def test_ge_and_gt_differ_at_boundary() -> None:
    """`ge` と `gt` は `x == k` の扱いだけが違う（固定入力集合の識別力の要件）。"""
    assert OP_IMPLS["ge"](DUPS, 5) == [5, 5]
    assert OP_IMPLS["gt"](DUPS, 5) == []


def test_le_and_lt_differ_at_boundary() -> None:
    """`le` と `lt` は `x == k` の扱いだけが違う。"""
    assert OP_IMPLS["le"](DUPS, 5) == [5, 5, -5, 0]
    assert OP_IMPLS["lt"](DUPS, 5) == [-5, 0]


def test_lt_at_1_differs_from_negative() -> None:
    """`lt`@1 は `negative` と違う。ゼロを含む（改訂版 L277）。

    この差があるためリテラル @1 を除外していない。除外してしまうと課題文に反する。
    """
    assert OP_IMPLS["lt"](MIXED, 1) == [-3, -2, -1, 0]
    assert OP_IMPLS["negative"](MIXED, 1) == [-3, -2, -1]


def test_ops_return_new_list() -> None:
    """全opが新しいリストを返す（入力と同一オブジェクトを返さない）。

    同一オブジェクトを返すと、`run()` の途中で前段の結果を共有してしまう。
    """
    for name, impl in OP_IMPLS.items():
        source = [3, 1, 2]
        result = impl(source, 2)
        assert result is not source, name
        assert isinstance(result, list), name


def test_ops_return_ints_only() -> None:
    """出力要素が `int` のままである（`bool` や `float` に化けない）。"""
    for name, impl in OP_IMPLS.items():
        for value in impl(MIXED, 3):
            assert type(value) is int, name


def test_multiple_of_asserts_k_lower_bound() -> None:
    """`multiple_of` は `k >= 1` を assert する（ゼロ除算の防止、実装計画 §6）。"""
    with pytest.raises(AssertionError):
        OP_IMPLS["multiple_of"]([1, 2, 3], 0)


def test_take_last_asserts_k_lower_bound() -> None:
    """`take_last` は `k >= 1` を assert する（実装計画 §6）。

    `xs[-0:]` は全リストを返すため、`k == 0` を黙って通すと「末尾0個」が
    「全部」になってしまう。assert がその罠を止めていることを固定する。
    """
    with pytest.raises(AssertionError):
        OP_IMPLS["take_last"]([1, 2, 3], 0)

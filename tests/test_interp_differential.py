"""参照インタプリタを**別の書き方の実装**と全数比較する（差分テスト）。

## なぜ必要か（実装計画 §7 に無い追加のテスト）

改訂版 L281-286 は参照インタプリタとコード生成器を独立に作り、両者の出力をランダムテストで
比較してバグを検出する仕掛けを求めている。しかしコード生成器は今回スコープ外（実装計画 §1）
なので、**この仕掛けはこのフェーズでは成立しない。**

残るガードは `test_interp_ops.py` の手書き期待値だけだが、そこには弱点がある。期待値を書いたのも
実装を書いたのも同じ人間なので、**思い違いがあれば両方に同じ形で入り込み、両方が揃って通る。**
`%` が負数でどう振る舞うかのような箇所は、まさにその種の思い違いが起きやすい。

そこで、意味を**意図的に違う原理で**もう一度書き、全数比較する。原理が違えば同じ思い違いは
共有されにくい。L281-286 の意図をこのフェーズで代替する位置づけであり、
コード生成器が実装されたらそちらが本来の差分テストを担う。

## 別実装で使う原理

| op | 本体 | このファイル |
| --- | --- | --- |
| `even` `odd` | `x % 2` | ビット検査 `x & 1`（剰余を使わない） |
| `multiple_of` | `x % k` | 床除算 `x // k * k == x` |
| `ge` `le` | `>=` `<=` | 否定した狭義比較 `not x < k` |
| `double` `triple` `mul_k` | 乗算 | 加算の繰り返し |
| `square` | `x * x` | 加算の繰り返し（符号は別途） |
| `asc` `desc` | `sorted` | 最小値／最大値の繰り返し取り出し |
| `reverse` | スライス `[::-1]` | 添字を降順に回すループ |
| `take_first` `take_last` `every_other` | スライス | 添字ループ（スライスを使わない） |
"""

from collections.abc import Callable, Sequence
from itertools import permutations, product

import pytest

from boku.interp.ops import OP_IMPLS
from boku.interp.run import run
from boku.limits import ELEM_MAX, ELEM_MIN, K_MAX, K_MIN


def alt_is_even(x: int) -> bool:
    """剰余を使わずビット検査で偶奇を決める。

    Pythonの整数は任意精度の2の補数として振る舞うため、負数でも `-3 & 1 == 1` となる。
    """
    return x & 1 == 0


def alt_is_multiple(x: int, k: int) -> bool:
    """剰余を使わず床除算で倍数を決める。"""
    return x // k * k == x


def alt_sort_asc(xs: Sequence[int]) -> list[int]:
    """`sorted` を使わず最小値を繰り返し取り出す。"""
    rest, out = list(xs), []
    while rest:
        smallest = rest[0]
        for value in rest:
            if value < smallest:
                smallest = value
        rest.remove(smallest)
        out.append(smallest)
    return out


def alt_sort_desc(xs: Sequence[int]) -> list[int]:
    """`sorted` を使わず最大値を繰り返し取り出す。"""
    rest, out = list(xs), []
    while rest:
        largest = rest[0]
        for value in rest:
            if value > largest:
                largest = value
        rest.remove(largest)
        out.append(largest)
    return out


def alt_reverse(xs: Sequence[int]) -> list[int]:
    """スライスを使わず添字を降順に回す。"""
    return [xs[i] for i in range(len(xs) - 1, -1, -1)]


def alt_take_first(xs: Sequence[int], k: int) -> list[int]:
    """スライスを使わず添字で判定する。`k > len(xs)` なら全件残る。"""
    return [xs[i] for i in range(len(xs)) if i < k]


def alt_take_last(xs: Sequence[int], k: int) -> list[int]:
    """スライスを使わず添字で判定する。`k > len(xs)` なら全件残る。"""
    return [xs[i] for i in range(len(xs)) if i >= len(xs) - k]


def alt_every_other(xs: Sequence[int], k: int) -> list[int]:
    """スライスを使わず添字の偶奇で判定する（先頭から）。"""
    return [xs[i] for i in range(len(xs)) if alt_is_even(i)]


def alt_repeated_add(x: int, times: int) -> int:
    """`x * times` を加算の繰り返しで求める（`times >= 0` 前提）。"""
    total = 0
    for _ in range(times):
        total += x
    return total


def alt_square(x: int) -> int:
    """`x * x` を加算の繰り返しで求める。符号は最後に決める。"""
    magnitude = alt_repeated_add(x, abs(x))
    return magnitude if x >= 0 else -magnitude


ALT_IMPLS: dict[str, Callable[[Sequence[int], int], list[int]]] = {
    "even": lambda xs, k: [x for x in xs if alt_is_even(x)],
    "odd": lambda xs, k: [x for x in xs if not alt_is_even(x)],
    "gt": lambda xs, k: [x for x in xs if x > k],
    "ge": lambda xs, k: [x for x in xs if not x < k],
    "lt": lambda xs, k: [x for x in xs if x < k],
    "le": lambda xs, k: [x for x in xs if not x > k],
    "multiple_of": lambda xs, k: [x for x in xs if alt_is_multiple(x, k)],
    "positive": lambda xs, k: [x for x in xs if x > 0],
    "negative": lambda xs, k: [x for x in xs if x < 0],
    "zero": lambda xs, k: [x for x in xs if not x > 0 and not x < 0],
    "add_k": lambda xs, k: [x + k for x in xs],
    "sub_k": lambda xs, k: [x + (-k) for x in xs],
    "mul_k": lambda xs, k: [alt_repeated_add(x, k) for x in xs],
    "double": lambda xs, k: [x + x for x in xs],
    "triple": lambda xs, k: [x + x + x for x in xs],
    "negate": lambda xs, k: [0 - x for x in xs],
    "abs": lambda xs, k: [x if x >= 0 else 0 - x for x in xs],
    "square": lambda xs, k: [alt_square(x) for x in xs],
    "asc": lambda xs, k: alt_sort_asc(xs),
    "desc": lambda xs, k: alt_sort_desc(xs),
    "reverse": lambda xs, k: alt_reverse(xs),
    "take_first": alt_take_first,
    "take_last": alt_take_last,
    "every_other": alt_every_other,
}


def alt_run(ast: Sequence[str], xs: Sequence[int], k: int) -> list[int]:
    """別実装で意味ASTを評価する。"""
    current = list(xs)
    for op_name in ast:
        current = ALT_IMPLS[op_name](current, k)
    return current


def test_alt_covers_all_ops() -> None:
    """別実装が24opすべてを覆う（片方だけ増えた状態を作らない）。"""
    assert set(ALT_IMPLS) == set(OP_IMPLS)


@pytest.mark.parametrize("op_name", sorted(OP_IMPLS))
def test_single_op_exhaustive_on_small_inputs(op_name: str) -> None:
    """要素 −4〜4・長さ 0〜3 の全入力 × `k` 1〜10 で一致する。

    小さいが**全数**なので、符号・ゼロ・重複・空リスト・`k > len(xs)` の組み合わせが
    取りこぼしなく入る。
    """
    impl = OP_IMPLS[op_name]
    alt = ALT_IMPLS[op_name]
    for length in range(4):
        for xs in product(range(-4, 5), repeat=length):
            for k in range(K_MIN, K_MAX + 1):
                assert impl(list(xs), k) == alt(list(xs), k), (op_name, xs, k)


@pytest.mark.parametrize("op_name", sorted(OP_IMPLS))
def test_single_op_on_boundary_elements(op_name: str) -> None:
    """L103 の境界（±100）を含む入力で一致する。"""
    wide = [ELEM_MIN, -99, -51, -50, -3, -2, -1, 0, 1, 2, 3, 50, 51, 99, ELEM_MAX]
    impl = OP_IMPLS[op_name]
    alt = ALT_IMPLS[op_name]
    for k in range(K_MIN, K_MAX + 1):
        assert impl(wide, k) == alt(wide, k), (op_name, k)


def test_three_op_sequences_match() -> None:
    """3opの操作列で `run()` と別実装が一致する。

    合成すると、変換で範囲外に出た値がフィルタに渡る（`mul_k` の出力を `even` が見るなど）。
    単一opの検査では通らない経路なので分けて持つ。
    """
    inputs: list[tuple[list[int], int]] = [
        ([], 1),
        ([0], 5),
        ([5, 5, -5, 0], 3),
        ([-3, -2, -1, 0, 1, 2, 3], 3),
        ([ELEM_MIN, ELEM_MAX], K_MAX),
        ([7, -7, 14, 0, 21], 7),
    ]
    sample_ops = [
        "even", "ge", "mul_k", "square", "asc", "desc",
        "reverse", "take_first", "take_last", "every_other", "abs", "negate",
    ]
    for ast in permutations(sample_ops, 3):
        for xs, k in inputs:
            assert run(list(ast), xs, k) == alt_run(ast, xs, k), (ast, xs, k)

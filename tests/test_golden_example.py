"""改訂版の「問題例」（L159-172）との一致（実装計画 §7）。

課題文が唯一示している具体例なので、参照インタプリタがこれを再現できることは最低条件である。

> 整数リストxsから、まずk以上の要素だけを残し、次にそれぞれを2倍して、最後に昇順に並べる
> solve関数を書いてください。（L163）

```python
def solve(xs: list[int], k: int) -> list[int]:
    return sorted([x * 2 for x in xs if x >= k])   # L168-169
```

対応する意味ASTは `["ge", "double", "asc"]`（L251）。

このテストは**課題文に載っているコードを期待値の側に置く**。参照インタプリタの実装を写して
きたのではなく、独立に書かれたコードとの一致を見ているので、意味の検査として機能する。
"""

import random

from boku.interp.run import run
from boku.limits import ELEM_MAX, ELEM_MIN, K_MAX, K_MIN, XS_LEN_MAX, XS_LEN_MIN

GOLDEN_AST = ["ge", "double", "asc"]


def spec_solve(xs: list[int], k: int) -> list[int]:
    """改訂版 L168-169 に掲載されているコードそのまま。"""
    return sorted([x * 2 for x in xs if x >= k])


def test_matches_spec_code_on_the_documented_example() -> None:
    """課題文の指示文に対応する具体的な入出力。"""
    xs = [1, 5, 3, 8, 2]
    k = 3
    assert run(GOLDEN_AST, xs, k) == [6, 10, 16]
    assert run(GOLDEN_AST, xs, k) == spec_solve(xs, k)


def test_matches_spec_code_on_random_inputs() -> None:
    """ランダム入力1,000件で完全一致（実装計画 §7）。

    入力は L102-104 の範囲から生成する。長さ0（空リスト）も含む。
    """
    rng = random.Random(0)
    for _ in range(1000):
        length = rng.randint(XS_LEN_MIN, XS_LEN_MAX)
        xs = [rng.randint(ELEM_MIN, ELEM_MAX) for _ in range(length)]
        k = rng.randint(K_MIN, K_MAX)
        assert run(GOLDEN_AST, xs, k) == spec_solve(xs, k), (xs, k)


def test_matches_spec_code_on_boundary_inputs() -> None:
    """境界値（L514 の境界値テストに相当）。"""
    boundary_cases: list[tuple[list[int], int]] = [
        ([], 1),                                  # 空リスト
        ([], 10),
        ([0], 1),                                 # ge@1 の境界。0 は残らない
        ([1], 1),                                 # x == k は残る
        ([-100] * 20, 1),                         # 全要素が不合格
        ([100] * 20, 10),                         # 全要素が合格・全て同値
        ([ELEM_MIN, ELEM_MAX], 10),
        ([-1, 0, 1], 1),
    ]
    for xs, k in boundary_cases:
        assert run(GOLDEN_AST, xs, k) == spec_solve(xs, k), (xs, k)


def test_order_matters() -> None:
    """操作の順序が意味を持つ（改訂版 L297-302）。

    課題文が挙げている例をそのまま検査する。

        [asc, take_first]   昇順に並べてから先頭k個を取る
        [take_first, asc]   先頭k個を取ってから昇順に並べる

    この二つが同じ結果になってしまう実装は、順序を無視していることになる。
    """
    xs = [5, 1, 9, 3]
    k = 2
    assert run(["asc", "take_first"], xs, k) == [1, 3]
    assert run(["take_first", "asc"], xs, k) == [1, 5]


def test_sorting_is_not_only_last_one_that_matters() -> None:
    """「並べ替えは最後のものだけが効く」は偽（実装計画 §2.7）。

    `[asc, take_first, desc]` の `asc` は `take_first` が何を取るかを決めているので効いている。
    構造的な枝刈りを書いてはいけない根拠であり、その前提を固定する。
    """
    xs = [5, 1, 9, 3]
    k = 2
    assert run(["asc", "take_first", "desc"], xs, k) == [3, 1]
    assert run(["take_first", "desc"], xs, k) == [5, 1]

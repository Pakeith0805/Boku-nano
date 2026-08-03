"""`run()` と各opが入力を変更しないことの検査（実装計画 §5, §7）。

破壊的変更が混ざると、`behavior_hash` の算出で同じ入力を使い回した際に前の評価の影響が残り、
固定入力集合（全レコードで共通、改訂版 L536）が壊れる。静かに壊れるので機械的に止める。
"""

from boku.interp.ops import OP_IMPLS
from boku.interp.run import run

SAMPLE = [5, 5, -5, 0, 3]


def test_run_does_not_mutate_xs() -> None:
    """`run()` が引数 `xs` を変更しない。"""
    xs = list(SAMPLE)
    run(["asc", "take_first", "desc"], xs, 3)
    assert xs == SAMPLE


def test_run_result_is_not_the_input_object() -> None:
    """`run()` の戻り値が引数と同一オブジェクトでない。

    恒等になる空ASTでも複製を返す（呼び出し元が結果を書き換えても入力に響かない）。
    """
    xs = list(SAMPLE)
    result = run([], xs, 3)
    assert result == SAMPLE
    assert result is not xs


def test_every_op_does_not_mutate_xs() -> None:
    """24op すべてが引数を変更しない。"""
    for name, impl in OP_IMPLS.items():
        xs = list(SAMPLE)
        impl(xs, 3)
        assert xs == SAMPLE, name


def test_repeated_run_is_stable() -> None:
    """同じ入力で繰り返し評価しても結果が変わらない（副作用がない）。

    改訂版 L107 の「副作用を持たない純粋関数」に対応する。
    """
    ast = ["even", "add_k", "desc", "take_first"]
    xs = list(SAMPLE)
    first = run(ast, xs, 3)
    for _ in range(3):
        assert run(ast, xs, 3) == first

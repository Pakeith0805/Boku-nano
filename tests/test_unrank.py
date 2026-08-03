"""順位付けの全数検査（実装計画 §7, §2.2）。

`unrank` は意味AST空間を展開せずに番号からASTを復元する。番号づけが1対1でないと、
層化抽出（#7）が同じASTを二度選んだり、一部のASTに到達できなくなったりする。
静かに壊れるので**全数**で確認する。

`itertools.permutations` との突き合わせも行う。あちらは標準ライブラリの独立した実装なので、
下降階乗基数の桁の重みを間違えていれば食い違いとして出る。
"""

from collections import Counter
from itertools import permutations
from math import perm

import pytest

from boku.semantics.registry import MAX_OPS, N_OPS, OP_NAMES
from boku.semantics.semantic_ast import SemanticAST
from boku.semantics.unrank import (
    COUNTS_BY_DIFFICULTY,
    TOTAL_COUNT,
    count,
    rank,
    unrank,
)
from boku.semantics.validate import is_valid

ALL_BY_DIFFICULTY: dict[int, list[tuple[str, ...]]] = {
    r: [unrank(r, i) for i in range(count(r))] for r in range(1, MAX_OPS + 1)
}
"""全空間を一度だけ展開したもの。テスト内でのみ使う（本体は展開しない）。"""


def test_counts_match_the_spec() -> None:
    """difficulty ごとの個数が改訂版 L405-411 のとおり。"""
    assert count(1) == 24
    assert count(2) == 552
    assert count(3) == 12_144
    assert count(4) == 255_024
    assert COUNTS_BY_DIFFICULTY == {1: 24, 2: 552, 3: 12_144, 4: 255_024}


def test_total_is_267744() -> None:
    """合計が 267,744（改訂版 L410）。"""
    assert TOTAL_COUNT == 267_744
    assert sum(len(items) for items in ALL_BY_DIFFICULTY.values()) == 267_744


def test_counts_equal_falling_factorial() -> None:
    """個数が下降階乗（順序付き・重複なし）と一致する。"""
    for r in range(1, MAX_OPS + 1):
        assert count(r) == perm(N_OPS, r)


@pytest.mark.parametrize("difficulty", range(1, MAX_OPS + 1))
def test_roundtrip_over_the_whole_space(difficulty: int) -> None:
    """`rank(unrank(r, i)) == i` が全番号で成立する（実装計画 §7）。"""
    for index, ops in enumerate(ALL_BY_DIFFICULTY[difficulty]):
        assert rank(ops) == index, (difficulty, index, ops)


@pytest.mark.parametrize("difficulty", range(1, MAX_OPS + 1))
def test_image_has_no_duplicates(difficulty: int) -> None:
    """`unrank` の像に重複がない（番号とASTが1対1）。"""
    items = ALL_BY_DIFFICULTY[difficulty]
    assert len(set(items)) == len(items)


@pytest.mark.parametrize("difficulty", range(1, MAX_OPS + 1))
def test_no_repeated_op_within_an_ast(difficulty: int) -> None:
    """1つのASTに同じopが二度現れない（改訂版 L111）。"""
    for ops in ALL_BY_DIFFICULTY[difficulty]:
        assert len(set(ops)) == len(ops) == difficulty, ops


@pytest.mark.parametrize("difficulty", range(1, MAX_OPS + 1))
def test_matches_itertools_permutations(difficulty: int) -> None:
    """標準ライブラリの独立実装と順序まで一致する。

    `itertools.permutations` はソート済み入力に対して辞書順に並びを返す。
    桁の重みを取り違えていれば、同じ集合でも順序が食い違うので検出できる。
    """
    for index, expected in enumerate(permutations(OP_NAMES, difficulty)):
        assert unrank(difficulty, index) == expected, (difficulty, index)


@pytest.mark.parametrize("difficulty", range(1, MAX_OPS + 1))
def test_every_ast_passes_structural_validation(difficulty: int) -> None:
    """列挙器が構造的に不正なASTを作らない（実装計画 §9 の期待出力）。

    #3 の検証器との突き合わせ。片方だけ壊れたら落ちる。
    """
    for ops in ALL_BY_DIFFICULTY[difficulty]:
        assert is_valid(SemanticAST(ops)), ops


@pytest.mark.parametrize("difficulty", range(1, MAX_OPS + 1))
def test_op_frequency_is_exactly_uniform(difficulty: int) -> None:
    """全数を取ると各opの出現回数が厳密に等しい（実装計画 §2.2）。

    24個のopが互いに対称であることの帰結であり、改訂版 L458「各演算子の出現頻度を均す」が
    **追加処理なしで**満たされる根拠。1opあたり `r × perm(23, r-1)` 回現れる。
    """
    counter: Counter[str] = Counter()
    for ops in ALL_BY_DIFFICULTY[difficulty]:
        counter.update(ops)

    expected = difficulty * perm(N_OPS - 1, difficulty - 1)
    assert set(counter) == set(OP_NAMES)
    assert set(counter.values()) == {expected}
    assert sum(counter.values()) == count(difficulty) * difficulty


def test_op_frequency_for_difficulty_4() -> None:
    """difficulty 4 では各opがちょうど 42,504 回（= 4 × 23×22×21）。"""
    counter: Counter[str] = Counter()
    for ops in ALL_BY_DIFFICULTY[4]:
        counter.update(ops)
    assert set(counter.values()) == {42_504}
    assert 4 * 23 * 22 * 21 == 42_504


def test_first_and_last_of_each_difficulty() -> None:
    """先頭と末尾が辞書順の両端になる。"""
    assert unrank(1, 0) == (OP_NAMES[0],)
    assert unrank(1, count(1) - 1) == (OP_NAMES[-1],)
    assert unrank(2, 0) == (OP_NAMES[0], OP_NAMES[1])
    assert unrank(2, count(2) - 1) == (OP_NAMES[-1], OP_NAMES[-2])
    assert unrank(4, 0) == tuple(OP_NAMES[:4])
    assert unrank(4, count(4) - 1) == tuple(reversed(OP_NAMES[-4:]))


def test_documented_example_from_the_plan() -> None:
    """モジュールの docstring が挙げている例。"""
    assert unrank(3, 0) == ("abs", "add_k", "asc")
    assert rank(("abs", "add_k", "asc")) == 0


def test_rank_accepts_every_op_as_a_singleton() -> None:
    """単一opのASTが 0〜23 に並ぶ（辞書順）。"""
    for index, name in enumerate(OP_NAMES):
        assert unrank(1, index) == (name,)
        assert rank((name,)) == index


@pytest.mark.parametrize("difficulty", [0, -1, MAX_OPS + 1, 99])
def test_unrank_rejects_invalid_difficulty(difficulty: int) -> None:
    """difficulty が 1〜4 の外なら `ValueError`（改訂版 L111）。"""
    with pytest.raises(ValueError, match="difficulty"):
        unrank(difficulty, 0)
    with pytest.raises(ValueError, match="difficulty"):
        count(difficulty)


@pytest.mark.parametrize("difficulty", range(1, MAX_OPS + 1))
def test_unrank_rejects_out_of_range_index(difficulty: int) -> None:
    """番号が範囲外なら `IndexError`。"""
    with pytest.raises(IndexError):
        unrank(difficulty, count(difficulty))
    with pytest.raises(IndexError):
        unrank(difficulty, -1)


def test_rank_rejects_unknown_op() -> None:
    """未知のop名を弾く。"""
    with pytest.raises(ValueError, match="未知のop名"):
        rank(("even", "sort_descending"))


def test_rank_rejects_duplicate_op() -> None:
    """同一opの重複を弾く（改訂版 L111）。

    弾かずに通すと、別のASTを指す番号を静かに返してしまう。
    """
    with pytest.raises(ValueError, match="重複"):
        rank(("even", "even"))


def test_rank_rejects_invalid_length() -> None:
    """長さが 1〜4 の外なら `ValueError`。"""
    with pytest.raises(ValueError, match="difficulty"):
        rank(())
    with pytest.raises(ValueError, match="difficulty"):
        rank(("even", "odd", "asc", "desc", "reverse"))


def test_unrank_does_not_depend_on_call_order() -> None:
    """呼び出しに状態が残らない（同じ番号は常に同じASTを返す）。

    `remaining` の作り直しを忘れると、2回目以降が壊れる。
    """
    first = [unrank(3, i) for i in (0, 100, 5000, 12_143)]
    _ = [unrank(4, i) for i in range(50)]
    second = [unrank(3, i) for i in (0, 100, 5000, 12_143)]
    assert first == second

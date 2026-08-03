"""`uniform_literal_domain` の全数検査（実装計画 §7, §2.4）。

意味AST空間 267,744件を**全数**回して、共通部分の計算と、実装計画 §2.4 が主張する数値を
確認する。§2.4 の議論（「共通部分が空になるASTは存在せず最小7なので、制約を課しても
展開の余地は失われない」）がここに乗っているため、主張ごと機械的に固定する。
"""

from collections import Counter
from itertools import permutations

import pytest

from boku.semantics.registry import LITERAL_MAX, LITERAL_MIN, MAX_OPS, OP_NAMES, OP_REGISTRY
from boku.semantics.semantic_ast import SemanticAST

K_OPS = frozenset(name for name, spec in OP_REGISTRY.items() if spec.uses_k)


def all_asts() -> list[SemanticAST]:
    """意味AST空間の全件（1〜`MAX_OPS` op の順列）。

    `unrank.py`（#4）はまだ無いので `itertools.permutations` で直接作る。
    列挙器の実装とは独立に空間を作ることになるので、後で `test_unrank.py` と
    突き合わせる材料にもなる。
    """
    return [
        SemanticAST(ops)
        for r in range(1, MAX_OPS + 1)
        for ops in permutations(OP_NAMES, r)
    ]


ALL_ASTS = all_asts()


def test_space_size() -> None:
    """空間の大きさが 267,744（実装計画 §2.2、改訂版 L405-411）。"""
    assert len(ALL_ASTS) == 267_744


def test_uniform_domain_is_the_intersection_of_slot_domains() -> None:
    """全ASTで、共通部分の計算が各スロット値域の積集合と一致する。"""
    for ast in ALL_ASTS:
        slots = ast.binding_slots
        if not slots:
            assert ast.uniform_literal_domain == (), str(ast)
            continue
        expected = set(range(LITERAL_MIN, LITERAL_MAX + 1))
        for slot in slots:
            expected &= set(slot.literal_domain)
        assert ast.uniform_literal_domain == tuple(sorted(expected)), str(ast)


def test_uniform_domain_is_never_empty_and_at_least_7() -> None:
    """`k` を使うASTでは共通部分が必ず非空で、最小7値（実装計画 §2.4）。

    除外がすべて値域の下限側にあり、最大の除外集合が `mul_k` の {1, 2, 3} であることに
    乗っている。除外の形が変わったら §2.4 の主張を再検証する必要がある。
    """
    sizes = [
        len(ast.uniform_literal_domain) for ast in ALL_ASTS if ast.uses_k
    ]
    assert min(sizes) == 7
    assert max(sizes) == 10
    assert all(size > 0 for size in sizes)


def test_k_slot_distribution() -> None:
    """`k` 参照スロット数の分布（実装計画 §2.4 の表）。

    2個以上が 148,230件＝空間の 55.4%。一様具体化の制約が例外ではなく既定の経路である、
    という §2.4 の主張の根拠。
    """
    distribution = Counter(len(ast.binding_slots) for ast in ALL_ASTS)
    assert dict(sorted(distribution.items())) == {
        0: 26_404,
        1: 93_110,
        2: 102_150,
        3: 41_040,
        4: 5_040,
    }
    multi = sum(count for slots, count in distribution.items() if slots >= 2)
    assert multi == 148_230
    assert round(100 * multi / len(ALL_ASTS), 1) == 55.4


def test_non_k_ast_count() -> None:
    """`k` 参照opを持たないASTが 26,404件＝9.9%（実装計画 §2.4 の申し送り）。

    14 + 14·13 + 14·13·12 + 14·13·12·11 の和。これらはバインディングによる多様性が
    ゼロなので、展開層は日本語表現とコード形式だけで例数を満たす必要がある。
    """
    non_k = [ast for ast in ALL_ASTS if not ast.uses_k]
    assert len(non_k) == 26_404
    assert round(100 * len(non_k) / len(ALL_ASTS), 1) == 9.9
    assert all(ast.uniform_literal_domain == () for ast in non_k)


def test_narrowest_example() -> None:
    """実装計画 §2.4 が挙げている最狭の例。"""
    ast = SemanticAST(("ge", "multiple_of", "mul_k"))
    assert ast.uniform_literal_domain == (4, 5, 6, 7, 8, 9, 10)
    assert len(ast.binding_slots) == 3


@pytest.mark.parametrize(
    ("ops", "expected"),
    [
        (("ge",), tuple(range(2, 11))),
        (("multiple_of",), tuple(range(3, 11))),
        (("mul_k",), tuple(range(4, 11))),
        (("take_first",), tuple(range(1, 11))),
        (("ge", "mul_k"), tuple(range(4, 11))),
        (("ge", "multiple_of"), tuple(range(3, 11))),
        (("gt", "le", "take_last"), tuple(range(1, 11))),
        (("even", "asc"), ()),
    ],
)
def test_specific_intersections(ops: tuple[str, ...], expected: tuple[int, ...]) -> None:
    """代表的な組み合わせの共通部分を手で確認する。"""
    assert SemanticAST(ops).uniform_literal_domain == expected


def test_slot_index_matches_position_in_ast() -> None:
    """スロットの `index` がAST内の位置と一致する。

    同じopでも位置が違えば別スロットなので、位置がずれると展開層が壊れる。
    """
    ast = SemanticAST(("even", "ge", "asc", "take_first"))
    assert [(slot.index, slot.op) for slot in ast.binding_slots] == [
        (1, "ge"),
        (3, "take_first"),
    ]


def test_every_k_op_appears_as_a_slot() -> None:
    """`uses_k=True` のopがすべてスロットとして現れる（取りこぼしがない）。"""
    for name in sorted(K_OPS):
        ast = SemanticAST(("even", name))
        assert [slot.op for slot in ast.binding_slots] == [name]
        assert ast.uniform_literal_domain == OP_REGISTRY[name].literal_domain

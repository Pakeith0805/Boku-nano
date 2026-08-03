"""一様具体化の等価性（実装計画 §7, §2.4）。

改訂版 L269 はリテラル具体化の検証をこう根拠づけている。

> リテラル版のコードは必ず「参照インタプリタを`k`＝そのリテラル値で評価した結果」と一致するため、
> パラメータ版とまったく同じ検証機構をそのまま適用できる。

**この等価性が成立するのは、ASTが持つ `k` 参照スロットを全て同じ値に具体化した場合だけである。**
スロットごとに別の値を入れると、どの `k` での評価とも一致しなくなり、参照インタプリタで
正誤を判定できない。実装計画 §2.4 はこれを制約として明記し、`uniform_literal_domain` を
レコードに持たせている。

このファイルはその制約が**本物である**ことを反例で固定する。制約が絵に描いた餅なら、
展開層（今回スコープ外）がスロットごとに別の値を入れてしまい、検証が静かに壊れる。
"""

from collections.abc import Mapping, Sequence
from itertools import product

from boku.interp.ops import OP_IMPLS
from boku.interp.run import run
from boku.limits import K_MAX, K_MIN
from boku.semantics.semantic_ast import SemanticAST

MULTI_SLOT_SAMPLES: tuple[tuple[str, ...], ...] = (
    ("ge", "take_first"),
    ("gt", "add_k"),
    ("multiple_of", "mul_k"),
    ("le", "sub_k", "take_last"),
    ("ge", "multiple_of", "mul_k"),
    ("even", "gt", "add_k", "take_first"),
)

INPUTS: tuple[list[int], ...] = (
    [],
    [0],
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    [-5, -1, 0, 1, 5, 10],
    [7, 7, -7, 0, 14, 21],
    [-100, -50, 0, 50, 100],
)


def eval_with_slot_values(
    ast: SemanticAST, xs: Sequence[int], k: int, slot_values: Mapping[int, int]
) -> list[int]:
    """スロットごとに別の値を入れて評価する。

    **本体には無い機能である。** 参照インタプリタは全opに同じ `k` を渡す設計なので
    （実装計画 §5）、混在バインディングを評価するにはこうした別経路が要る。
    展開層が「スロットごとに別のリテラルを入れる」実装をしたらこうなる、という模擬。

    `slot_values` に無い位置は `k` をそのまま使う。
    """
    current = list(xs)
    for index, name in enumerate(ast.ops):
        current = OP_IMPLS[name](current, slot_values.get(index, k))
    return current


def uniform_binding(ast: SemanticAST, value: int) -> dict[int, int]:
    """全スロットを同じ値に固定するバインディング。"""
    return {slot.index: value for slot in ast.binding_slots}


def test_uniform_binding_equals_run_at_that_value() -> None:
    """全スロットを `v` に固定した評価は `run(ast, xs, v)` と一致する（L269）。

    スロット別に値を渡す経路を通しても結果が変わらないことの確認であり、
    「リテラル版はパラメータ版と同じ検証機構で判定できる」という主張の中身にあたる。
    """
    for ops in MULTI_SLOT_SAMPLES:
        ast = SemanticAST(ops)
        for value in ast.uniform_literal_domain:
            for xs in INPUTS:
                assert eval_with_slot_values(
                    ast, xs, value, uniform_binding(ast, value)
                ) == run(ast.ops, xs, value), (ops, value, xs)


def test_mixed_binding_is_not_reproducible_by_any_k() -> None:
    """**反例**：スロットごとに違う値を入れると、どの `k` の評価とも一致しない。

    `[ge, take_first]` の `ge` を3、`take_first` を7に具体化する。

        xs = [1..10]
        ge@3        -> [3,4,5,6,7,8,9,10]
        take_first@7 -> [3,4,5,6,7,8,9]

    一方 `run(["ge","take_first"], xs, k)` は `k` を両方に渡すので、
    `k=3` なら `[3,4,5]`、`k=7` なら `[7,8,9,10]` になる。
    1〜10 のどの `k` でも上の結果は再現できない。
    つまりこのコードは参照インタプリタで正誤を判定できず、L269 の検証機構から外れる。
    """
    ast = SemanticAST(("ge", "take_first"))
    xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    mixed = eval_with_slot_values(ast, xs, K_MIN, {0: 3, 1: 7})
    assert mixed == [3, 4, 5, 6, 7, 8, 9]

    reachable = [run(ast.ops, xs, k) for k in range(K_MIN, K_MAX + 1)]
    assert mixed not in reachable
    assert run(ast.ops, xs, 3) == [3, 4, 5]
    assert run(ast.ops, xs, 7) == [7, 8, 9, 10]


def find_unverifiable_binding(
    ast: SemanticAST,
) -> tuple[dict[int, int], list[int], list[int]] | None:
    """どの `k` の評価とも一致しない混在バインディングを探す。

    見つかれば `(バインディング, 入力, 出力)`、無ければ `None`。
    バインディングは `uniform_literal_domain` の値の全組み合わせから、一様なものを除いて作る。
    """
    slots = ast.binding_slots
    domain = ast.uniform_literal_domain
    for values in product(domain, repeat=len(slots)):
        if len(set(values)) == 1:
            continue
        binding = {slot.index: value for slot, value in zip(slots, values)}
        for xs in INPUTS:
            mixed = eval_with_slot_values(ast, xs, domain[0], binding)
            if all(mixed != run(ast.ops, xs, k) for k in range(K_MIN, K_MAX + 1)):
                return binding, xs, mixed
    return None


def test_mixed_bindings_are_unverifiable_across_the_sample() -> None:
    """複数スロットASTで、検証不能になる混在バインディングが実際に存在する。

    反例が1つの特殊な組み合わせに限った話ではないことを示す。
    """
    for ops in MULTI_SLOT_SAMPLES:
        ast = SemanticAST(ops)
        assert len(ast.uniform_literal_domain) >= 2, ops
        assert find_unverifiable_binding(ast) is not None, ops


def test_some_asts_have_no_unverifiable_mixed_binding() -> None:
    """**逆に、混在バインディングが全て再現できてしまうASTも存在する。**

    `[gt, ge]` がそれである。理屈はこうなる。

        混在 gt@a → ge@b   は  x > a かつ x >= b
                            整数なので x >= b は x > b-1 と同じ
                            まとめて x > max(a, b-1)
        一様 gt@k → ge@k   は  x > k かつ x >= k = x > k

    `a`・`b` は値域 2〜10 なので `max(a, b-1)` は必ず 2〜10 に収まり、
    **どの混在バインディングも `k = max(a, b-1)` の一様版で再現できる。**

    これは制約が要らないという話ではなく、**逆に制約を全ASTに一律でかける根拠**である。
    安全かどうかはASTごとに違い、事前には分からない。個別に確認するには
    ここでやったような全探索が要る。それを毎回やる代わりに、
    「全スロット同一値」に限る（実装計画 §2.4）という一律の規則で済ませている。
    """
    for ops in (("gt", "ge"), ("ge", "gt")):
        ast = SemanticAST(ops)
        assert find_unverifiable_binding(ast) is None, ops


def test_uniform_values_outside_the_domain_still_evaluate() -> None:
    """値域外の値でも**評価自体はできる**（除外の理由は別にある）。

    `ge` のリテラル値域が 2〜10 なのは、@1 が `positive` と同じ関数になってしまうからで
    あって（改訂版 L275）、`run(ast, xs, 1)` が壊れるからではない。この二つを混同すると、
    `k` の値域（L104 の1〜10）まで狭めてしまう。

    固定入力集合は `k` を1〜10で網羅する必要があるので（実装計画 §2.5）、この区別は重要。
    """
    ast = SemanticAST(("ge", "double"))
    assert 1 not in ast.uniform_literal_domain
    assert run(ast.ops, [0, 1, 2], 1) == [2, 4]
    assert run(("positive", "double"), [0, 1, 2], 1) == [2, 4]


def test_parameter_version_is_verifiable_at_every_k() -> None:
    """全スロットを `k` のまま残した版は、任意の `k` で検証できる（§2.4 の形態1）。"""
    for ops in MULTI_SLOT_SAMPLES:
        ast = SemanticAST(ops)
        for k in range(K_MIN, K_MAX + 1):
            for xs in INPUTS:
                assert eval_with_slot_values(ast, xs, k, {}) == run(ast.ops, xs, k)

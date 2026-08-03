"""レジストリが改訂版 L113-157 の表に一致することの検査（実装計画 §7）。

期待値はレジストリから導出せず、改訂版の表を**独立に書き写す**。レジストリの値から計算すると
常に真になり検査にならないため、二重記述を意図的に許している。改訂版の表が変わったときに
このファイルとレジストリの両方を直す手間は、写し間違いを検出できる利得に見合う。

このファイルが検査するのは「存在と形式」だけであり、**意味が合っているかは検査しない**。
意味の検査は `test_interp_ops.py` と差分ランダムテストの担当である（実装計画 §2.8）。
"""

import pytest

from boku.interp.ops import OP_IMPLS
from boku.semantics.registry import (
    CATEGORY_ORDER,
    MAX_OPS,
    N_OPS,
    OP_NAMES,
    OP_REGISTRY,
    OpSpec,
)

# 改訂版 L117-157 の表の書き写し。値は (カテゴリ, `k`を参照するか)。
# `k` を参照するかは各行の「内容」列が `k` に言及しているかで決めた。
SPEC_TABLE: dict[str, tuple[str, bool]] = {
    # 抽出（L115「抽出（10種類）」、表は L117-128）
    "even": ("filter", False),           # 偶数だけを残す
    "odd": ("filter", False),            # 奇数だけを残す
    "gt": ("filter", True),              # `k`より大きい値を残す
    "ge": ("filter", True),              # `k`以上の値を残す
    "lt": ("filter", True),              # `k`より小さい値を残す
    "le": ("filter", True),              # `k`以下の値を残す
    "multiple_of": ("filter", True),     # `k`の倍数だけを残す
    "positive": ("filter", False),       # 正の要素を残す
    "negative": ("filter", False),       # 負の要素を残す
    "zero": ("filter", False),           # ゼロの要素を残す
    # 変換（L130「変換（8種類）」、表は L132-141）
    "add_k": ("map", True),              # 各要素に`k`を加える
    "sub_k": ("map", True),              # 各要素から`k`を引く
    "mul_k": ("map", True),              # 各要素に`k`を掛ける
    "double": ("map", False),            # 各要素を2倍する
    "triple": ("map", False),            # 各要素を3倍する
    "negate": ("map", False),            # 符号を反転する
    "abs": ("map", False),               # 絶対値を取る
    "square": ("map", False),            # 二乗する
    # 並べ替え（L143「並べ替え（3種類）」、表は L145-149）
    "asc": ("order", False),             # 昇順に並べる
    "desc": ("order", False),            # 降順に並べる
    "reverse": ("order", False),         # 逆順にする
    # 切り出し（L151「切り出し（3種類）」、表は L153-157）
    "take_first": ("slice", True),       # 先頭から`k`個
    "take_last": ("slice", True),        # 末尾から`k`個
    "every_other": ("slice", False),     # 1個おきに取得する
}

# 改訂版 L115 / L130 / L143 / L151 が見出しで宣言しているカテゴリ別の種類数。
SPEC_CATEGORY_COUNTS: dict[str, int] = {"filter": 10, "map": 8, "order": 3, "slice": 3}


def test_op_count_is_24() -> None:
    """opはちょうど24種類（改訂版 L111）。"""
    assert len(OP_REGISTRY) == 24
    assert N_OPS == 24


def test_op_names_match_spec_table() -> None:
    """op名の集合が改訂版の表と完全に一致する（過不足なし）。"""
    assert set(OP_REGISTRY) == set(SPEC_TABLE)


def test_categories_match_spec_table() -> None:
    """各opのカテゴリが改訂版の表と一致する。"""
    actual = {name: spec.category for name, spec in OP_REGISTRY.items()}
    expected = {name: category for name, (category, _) in SPEC_TABLE.items()}
    assert actual == expected


def test_uses_k_matches_spec_table() -> None:
    """各opの `k` 参照が改訂版の表と一致する。"""
    actual = {name: spec.uses_k for name, spec in OP_REGISTRY.items()}
    expected = {name: uses_k for name, (_, uses_k) in SPEC_TABLE.items()}
    assert actual == expected


def test_category_counts_match_spec_headings() -> None:
    """カテゴリ別の種類数が改訂版の見出しの宣言と一致する（10 / 8 / 3 / 3）。"""
    counts: dict[str, int] = {category: 0 for category in SPEC_CATEGORY_COUNTS}
    for spec in OP_REGISTRY.values():
        counts[spec.category] += 1
    assert counts == SPEC_CATEGORY_COUNTS
    assert sum(counts.values()) == 24


def test_uses_k_count_is_10() -> None:
    """`k` を参照するopが10、しないopが14（実装計画 §2.3）。

    この配分は `k` 参照opを持たないASTの件数 26,404 の根拠であり、
    `uniform_literal_domain` の設計（実装計画 §2.4）が乗っている。
    """
    uses_k = [name for name, spec in OP_REGISTRY.items() if spec.uses_k]
    assert len(uses_k) == 10
    assert len(OP_REGISTRY) - len(uses_k) == 14


def test_uses_k_iff_literal_domain_is_non_empty() -> None:
    """`uses_k=True` のopだけが非空の `literal_domain` を持つ（実装計画 §7）。

    `OpSpec` は両者を独立に手で書いているため、この検査は実質を持つ。
    """
    for name, spec in OP_REGISTRY.items():
        assert spec.uses_k == bool(spec.literal_domain), name


def test_registry_key_matches_spec_name() -> None:
    """`OP_REGISTRY` のキーと `OpSpec.name` が一致する（写し間違いの検出）。"""
    for key, spec in OP_REGISTRY.items():
        assert key == spec.name


def test_ja_key_is_present_and_unique() -> None:
    """`ja_key` が全opで非空かつ一意（日本語表現辞書の引き当てが衝突しない）。"""
    keys = [spec.ja_key for spec in OP_REGISTRY.values()]
    assert all(keys)
    assert len(set(keys)) == len(keys)


def test_shadows_reference_existing_ops() -> None:
    """`shadows` に書いた名前が実在するopである（実装計画 §2.6）。

    自分自身を指さないことも確認する。
    """
    for name, spec in OP_REGISTRY.items():
        for shadowed in spec.shadows:
            assert shadowed in OP_REGISTRY, (name, shadowed)
            assert shadowed != name


def test_shadows_match_spec_exclusions() -> None:
    """`shadows` が改訂版 L275 の「他の操作と同一になる値」と対応する。

    L275 が挙げるのは `multiple_of`@2 = `even`、`mul_k`@2 = `double`、
    `mul_k`@3 = `triple`、`ge`@1 = `positive` の4件。よって shadows を持つopは
    この3つだけであり、他のopは空でなければならない。
    """
    expected: dict[str, tuple[str, ...]] = {
        "ge": ("positive",),
        "multiple_of": ("even",),
        "mul_k": ("double", "triple"),
    }
    actual = {
        name: spec.shadows for name, spec in OP_REGISTRY.items() if spec.shadows
    }
    assert actual == expected


def test_categories_are_declared_in_category_order() -> None:
    """全opのカテゴリが `CATEGORY_ORDER` に含まれる（未知のカテゴリがない）。"""
    assert set(CATEGORY_ORDER) == set(SPEC_CATEGORY_COUNTS)
    for name, spec in OP_REGISTRY.items():
        assert spec.category in CATEGORY_ORDER, name


def test_op_names_is_sorted_and_complete() -> None:
    """`OP_NAMES` が辞書順で全opを含む（unrank の添字づけの安定性）。

    この並びが変わると同じ添字が別のASTを指すため、順序そのものを固定する。
    """
    assert OP_NAMES == tuple(sorted(SPEC_TABLE))
    assert len(OP_NAMES) == 24
    assert len(set(OP_NAMES)) == 24


def test_max_ops_is_4() -> None:
    """操作数の上限は4（改訂版 L111、実装計画 §8 確認事項①で確定）。"""
    assert MAX_OPS == 4


def test_op_spec_is_immutable() -> None:
    """`OpSpec` が凍結されている（レジストリを実行時に書き換えられない）。"""
    spec = OP_REGISTRY["even"]
    with pytest.raises((AttributeError, TypeError)):
        spec.name = "changed"  # type: ignore[misc]


def test_op_spec_holds_nothing_callable() -> None:
    """`OpSpec` が呼び出せるものを一切持たない（実装計画 §2.8）。

    レジストリに意味を置かないという要件を機械的に固定する。lambda や関数を
    フィールドに入れると、参照インタプリタとコード生成器が意味を共有してしまい、
    改訂版 L281-286 の差分ランダムテストが素通りする。
    """
    for name, spec in OP_REGISTRY.items():
        for field in OpSpec.__dataclass_fields__:
            value = getattr(spec, field)
            assert not callable(value), (name, field)


def test_every_op_has_an_interp_implementation() -> None:
    """全opに参照インタプリタの実装が存在し、逆も真（実装計画 §7）。

    レジストリと参照インタプリタを同期させる唯一のテストであり、意味を共有しない代償として
    必ず要る。ここが検査するのは**存在と形式だけ**で、意味が合っているかは見ない
    （実装計画 §2.8）。意味の検査は `test_interp_ops.py` の担当。
    """
    assert set(OP_IMPLS) == set(OP_REGISTRY)


def test_interp_impls_are_callable_with_the_uniform_signature() -> None:
    """全opの実装が `(xs, k)` の同じシグネチャで呼べる（実装計画 §5）。

    `uses_k` で呼び分けないという規約を固定する。呼び分けを導入すると、参照インタプリタが
    レジストリのメタデータに実行時依存してしまい、改訂版 L281-286 の独立性を損なう。
    """
    for name, impl in OP_IMPLS.items():
        assert callable(impl), name
        result = impl([1, 2, 3], 2)
        assert isinstance(result, list), name

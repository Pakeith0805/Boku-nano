"""固定入力集合の識別力の検査（実装計画 §7, §2.5）。

**単一opのAST 24個の出力列が全て相異なる**ことが受け入れ条件である。単一opすら分けられない
入力集合では、複合ASTの `behavior_hash` も信用できない。信用できない指紋で漏洩検査
（改訂版 L524 の第5項）を回すと、漏洩を見逃したまま「検査した」ことになってしまう。

凍結済みのファイル（`probes/behavior_probe_set_v1.jsonl`）に対して検査する。
生成器ではなく**実際に使う入力集合**を見ないと意味がない。
"""

from pathlib import Path

import pytest

from boku.limits import ELEM_MAX, ELEM_MIN, K_MAX, K_MIN, XS_LEN_MAX, XS_LEN_MIN
from boku.probes.behavior_probes import (
    MAX_PROBES,
    boundary_inputs,
    build_probe_set,
    default_probe_set_path,
    describe,
    indistinguishable_pairs,
    load_probe_inputs,
    load_probe_set,
    probe_outputs,
    single_op_outputs,
)
from boku.semantics.registry import OP_NAMES

ROOT = Path(__file__).resolve().parents[1]
FROZEN = default_probe_set_path(ROOT, "v1")
PROBES = load_probe_set(FROZEN)


def test_frozen_probe_set_exists() -> None:
    """凍結ファイルがある（`scripts.build_probe_set` の成果物）。"""
    assert FROZEN.exists(), f"{FROZEN} が無い。build_probe_set を実行すること"
    assert len(PROBES) > 0


def test_single_ops_are_all_distinguishable() -> None:
    """単一opのAST 24個の出力列が全て相異なる（実装計画 §2.5 の受け入れ条件）。"""
    assert indistinguishable_pairs(PROBES) == []
    outputs = single_op_outputs(PROBES)
    assert len(outputs) == 24
    assert len(set(outputs.values())) == 24


@pytest.mark.parametrize(
    ("left", "right", "reason"),
    [
        ("gt", "ge", "x == k を含む入力が要る"),
        ("lt", "le", "x == k を含む入力が要る"),
        ("mul_k", "double", "k ∉ {2, 3} の入力が要る"),
        ("mul_k", "triple", "k ∉ {2, 3} の入力が要る"),
        ("multiple_of", "even", "k ≠ 2 の入力が要る"),
        ("ge", "positive", "k ≠ 1 の入力が要る"),
        ("lt", "negative", "k = 1 かつ 0 を含む入力が要る"),
        ("take_first", "take_last", "len(xs) > k と len(xs) < k の両方が要る"),
        ("asc", "desc", "未整列で相異なる要素が要る"),
        ("asc", "reverse", "未整列で相異なる要素が要る"),
        ("desc", "reverse", "未整列で相異なる要素が要る"),
        ("negate", "abs", "負数が要る"),
        ("square", "abs", "絶対値と二乗が違う要素が要る"),
    ],
)
def test_specific_pairs_are_separated(left: str, right: str, reason: str) -> None:
    """実装計画 §2.5 が名指ししている紛らわしい組が実際に分かれている。

    全体の識別テストが通っていても、どの条件がどの組を分けているかは分からない。
    条件を1つ落としたときにどこが壊れるかを、この一覧が示す。
    """
    assert probe_outputs((left,), PROBES) != probe_outputs((right,), PROBES), reason


def test_k_covers_the_full_range() -> None:
    """`k` が 1〜10 を網羅する（実装計画 §2.5）。

    網羅していないと、リテラルに具体化した版の一部が覆えなくなる。改訂版 L269 の
    「リテラル版 ＝ `k` ＝そのリテラル値での評価」という性質がここに乗っている。
    """
    summary = describe(PROBES)
    assert summary["k_covers_full_range"] is True
    assert summary["k_values"] == list(range(K_MIN, K_MAX + 1))


def test_required_input_shapes_are_present() -> None:
    """実装計画 §2.5 が挙げている入力の形が揃っている。"""
    summary = describe(PROBES)
    assert summary["has_empty_xs"] is True
    assert summary["has_max_length_xs"] is True
    assert summary["has_x_equal_to_k"] is True
    assert summary["has_len_greater_than_k"] is True
    assert summary["has_len_less_than_k"] is True

    lengths = set(summary["xs_lengths"])  # type: ignore[arg-type]
    assert {0, 1, 2, 3, 5, 20} <= lengths


def test_required_element_patterns_are_present() -> None:
    """全負・全正・全ゼロ・重複値・正負混在が揃っている（実装計画 §2.5）。"""
    non_empty = [xs for xs, _ in PROBES if xs]
    assert any(all(x < 0 for x in xs) for xs in non_empty), "全負が無い"
    assert any(all(x > 0 for x in xs) for xs in non_empty), "全正が無い"
    assert any(all(x == 0 for x in xs) for xs in non_empty), "全ゼロが無い"
    assert any(len(xs) != len(set(xs)) for xs in non_empty), "重複値が無い"
    assert any(
        any(x > 0 for x in xs) and any(x < 0 for x in xs) for xs in non_empty
    ), "正負混在が無い"


def test_inputs_are_within_the_spec_ranges() -> None:
    """全入力が改訂版 L102-104 の範囲に収まる。"""
    for xs, k in PROBES:
        assert XS_LEN_MIN <= len(xs) <= XS_LEN_MAX, xs
        assert K_MIN <= k <= K_MAX, k
        for x in xs:
            assert ELEM_MIN <= x <= ELEM_MAX, x


def test_no_duplicate_probes() -> None:
    """入力に重複がない（同じ入力を二度評価しても識別力は増えない）。"""
    assert len(set(PROBES)) == len(PROBES)


def test_probe_count_within_limit() -> None:
    """件数が上限以内（実装計画 §2.5 の256）。"""
    assert len(PROBES) <= MAX_PROBES


def test_boundary_inputs_come_first() -> None:
    """境界値が先頭に並ぶ（凍結ファイルの `kind` と対応する）。"""
    boundary = boundary_inputs()
    assert len(boundary) == 20
    assert PROBES[: len(boundary)] == boundary


def test_build_is_deterministic() -> None:
    """同じ種なら同じ入力集合になる（実装計画 §3 の再現性）。"""
    first = build_probe_set(seed=20260730)
    second = build_probe_set(seed=20260730)
    assert first == second
    assert first == PROBES, "凍結ファイルが conf/probe_set.yaml の種と対応していない"


def test_different_seed_gives_different_set() -> None:
    """種が違えば入力集合も違う（種が効いていることの確認）。"""
    assert build_probe_set(seed=999) != PROBES


def test_load_probe_inputs_returns_a_set() -> None:
    """`load_probe_inputs()` が集合を返す（実装計画 §3）。

    将来の hidden test 生成器がこれを読み、衝突する `(xs, k)` を除外する。
    固定入力集合と hidden test が入力を共有すると、意味の同定に使った入力で評価することになる。
    """
    inputs = load_probe_inputs(FROZEN)
    assert isinstance(inputs, set)
    assert len(inputs) == len(PROBES)
    for xs, k in inputs:
        assert isinstance(xs, tuple)
        assert isinstance(k, int)


def test_load_preserves_order() -> None:
    """読み戻しで順序が保たれる。

    順序が変わると出力列も変わり、`behavior_hash` が全件変わってしまう。
    """
    assert load_probe_set(FROZEN) == PROBES


def test_probe_outputs_order_depends_on_probe_order() -> None:
    """出力列が入力の並びに依存する（凍結が必要な理由）。"""
    reversed_probes = list(reversed(PROBES))
    assert probe_outputs(("asc",), reversed_probes) != probe_outputs(("asc",), PROBES)


def test_every_op_appears_in_single_op_outputs() -> None:
    """24op すべてについて出力列が取れる。"""
    outputs = single_op_outputs(PROBES)
    assert set(outputs) == set(OP_NAMES)

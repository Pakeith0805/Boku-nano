"""層化抽出の検査（実装計画 §7, §2.2）。

改訂版 L416-421 の配分例をそのまま再現できること、目標件数の帯（L397）を守ること、
同じ種で再現できること（実装計画 §9 手順6）を固定する。
"""

import pytest

from boku.semantics.enumeration import (
    DEFAULT_TARGET,
    TARGET_MAX,
    TARGET_MIN,
    Allocation,
    allocation_from_counts,
    default_allocation,
    enumerate_asts,
    validate_target,
)
from boku.semantics.registry import MAX_OPS
from boku.semantics.unrank import TOTAL_COUNT, count
from boku.semantics.validate import is_valid

ALLOC_30K = default_allocation(30_000)


def test_default_allocation_matches_the_spec_example() -> None:
    """既定配分が改訂版 L417-421 のとおり。"""
    assert ALLOC_30K.as_dict() == {1: 24, 2: 552, 3: 12_144, 4: 17_280}
    assert ALLOC_30K.total == 30_000


def test_difficulty_1_to_3_are_exhaustive() -> None:
    """difficulty 1〜3 は全数（改訂版 L417-419 の「全数」）。"""
    for difficulty in (1, 2, 3):
        assert ALLOC_30K.is_exhaustive(difficulty)
        assert ALLOC_30K.for_difficulty(difficulty) == count(difficulty)
    assert not ALLOC_30K.is_exhaustive(4)


def test_difficulty_ratio_matches_the_spec() -> None:
    """1〜3操作 42% / 4操作 58%（改訂版 L421）。"""
    low = sum(ALLOC_30K.for_difficulty(d) for d in (1, 2, 3))
    assert low == 12_720
    assert round(100 * low / ALLOC_30K.total) == 42
    assert round(100 * ALLOC_30K.for_difficulty(4) / ALLOC_30K.total) == 58


def test_allocation_at_the_upper_end() -> None:
    """帯の上端 100,000 では difficulty 4 が 87,280 件（実装計画 §9 手順4）。"""
    allocation = default_allocation(TARGET_MAX)
    assert allocation.as_dict() == {1: 24, 2: 552, 3: 12_144, 4: 87_280}
    assert allocation.total == TARGET_MAX


def test_default_target_is_30000() -> None:
    """既定の目標件数（改訂版 L416）。"""
    assert DEFAULT_TARGET == 30_000
    assert (TARGET_MIN, TARGET_MAX) == (30_000, 100_000)


@pytest.mark.parametrize("target", [0, 1, 12_720, 29_999, 100_001, 267_744, 500_000])
def test_target_outside_the_band_is_rejected(target: int) -> None:
    """帯の外の目標件数を拒否する（改訂版 L397、実装計画 §2.2）。

    空間の上限（267,744）ではなく課題文の目安が境界。帯の外でコーパスを作れると、
    L424-437 の検算とデータ規模表の対応が黙って崩れる。
    """
    with pytest.raises(ValueError, match="target"):
        validate_target(target)
    with pytest.raises(ValueError, match="target"):
        default_allocation(target)


@pytest.mark.parametrize("target", [TARGET_MIN, 50_000, TARGET_MAX])
def test_target_inside_the_band_is_accepted(target: int) -> None:
    """帯の内側は通る（境界を含む）。"""
    validate_target(target)
    assert default_allocation(target).total == target


def test_explicit_allocation_matching_the_default() -> None:
    """明示指定が既定と一致する（実装計画 §2.2 の `alloc=[...]`）。"""
    allocation = allocation_from_counts([24, 552, 12_144, 17_280], target=30_000)
    assert allocation == ALLOC_30K


def test_explicit_allocation_must_sum_to_target() -> None:
    """合計が `target` と一致しなければ拒否（実装計画 §2.2）。"""
    with pytest.raises(ValueError, match="一致しない"):
        allocation_from_counts([24, 552, 12_144, 17_281], target=30_000)


def test_explicit_allocation_rejects_counts_beyond_the_space() -> None:
    """その difficulty に存在する数を超える要求を拒否する。"""
    with pytest.raises(ValueError, match="difficulty 1"):
        allocation_from_counts([25, 552, 12_144, 17_279], target=30_000)


def test_explicit_allocation_rejects_negative_counts() -> None:
    """負の件数を拒否する。"""
    with pytest.raises(ValueError, match="負"):
        allocation_from_counts([-1, 552, 12_144, 17_449], target=30_000)


def test_explicit_allocation_rejects_wrong_length() -> None:
    """difficulty の個数が合わなければ拒否する。"""
    with pytest.raises(ValueError, match=f"1〜{MAX_OPS}"):
        allocation_from_counts([24, 552, 12_144], target=30_000)


def test_explicit_allocation_must_stay_in_the_band() -> None:
    """明示指定でも帯の外なら拒否する（抜け道を作らない）。"""
    with pytest.raises(ValueError, match="target"):
        allocation_from_counts([24, 552, 12_144, 100])


# ---- 列挙 ----

ASTS = enumerate_asts(ALLOC_30K, seed=0)


def test_enumeration_count_matches_the_allocation() -> None:
    """列挙した件数が配分どおり。"""
    assert len(ASTS) == 30_000
    by_difficulty: dict[int, int] = {}
    for ast in ASTS:
        by_difficulty[ast.difficulty] = by_difficulty.get(ast.difficulty, 0) + 1
    assert by_difficulty == ALLOC_30K.as_dict()


def test_enumeration_has_no_duplicates() -> None:
    """同じASTを二度選ばない。"""
    assert len(set(ASTS)) == len(ASTS)


def test_every_enumerated_ast_is_structurally_valid() -> None:
    """列挙器が構造的に不正なASTを作らない（実装計画 §9 の期待出力）。"""
    assert all(is_valid(ast) for ast in ASTS)


def test_enumeration_is_reproducible() -> None:
    """同じ配分と種なら同じ並びになる（実装計画 §9 手順6）。"""
    assert enumerate_asts(ALLOC_30K, seed=0) == ASTS


def test_enumeration_is_sorted_within_each_difficulty() -> None:
    """difficulty の昇順、各層の中では番号の昇順に並ぶ。

    `random.sample` の戻り順に依存しないので、同じ番号集合なら常に同じ並びになる。
    #8 の `ast_id` 採番が安定する。
    """
    from boku.semantics.unrank import rank

    difficulties = [ast.difficulty for ast in ASTS]
    assert difficulties == sorted(difficulties)

    for difficulty in range(1, MAX_OPS + 1):
        ranks = [rank(ast.ops) for ast in ASTS if ast.difficulty == difficulty]
        assert ranks == sorted(ranks)


def test_different_seed_changes_only_the_sampled_layer() -> None:
    """種を変えると difficulty 4 だけが変わる。

    1〜3 は全数なので種に依存しない。ここが変わる実装は、全数の層まで抽出している。
    """
    other = enumerate_asts(ALLOC_30K, seed=1)
    for difficulty in (1, 2, 3):
        assert [a for a in ASTS if a.difficulty == difficulty] == [
            a for a in other if a.difficulty == difficulty
        ]
    assert [a for a in ASTS if a.difficulty == 4] != [
        a for a in other if a.difficulty == 4
    ]


def test_exhaustive_layers_cover_the_whole_space() -> None:
    """全数の層が本当にその空間の全件（取りこぼしがない）。"""
    from itertools import permutations

    from boku.semantics.registry import OP_NAMES

    for difficulty in (1, 2, 3):
        selected = {a.ops for a in ASTS if a.difficulty == difficulty}
        assert selected == set(permutations(OP_NAMES, difficulty))


def test_space_total_is_unchanged() -> None:
    """空間の大きさが 267,744 のまま（`MAX_OPS` を動かしていない）。"""
    assert TOTAL_COUNT == 267_744


def test_allocation_is_hashable_and_frozen() -> None:
    """`Allocation` が凍結されている（設定として持ち回れる）。"""
    assert hash(ALLOC_30K) == hash(Allocation((24, 552, 12_144, 17_280)))
    with pytest.raises((AttributeError, TypeError)):
        ALLOC_30K.counts = (1, 2, 3, 4)  # type: ignore[misc]

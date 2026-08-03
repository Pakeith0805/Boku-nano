"""op出現頻度の一様性の検査（実装計画 §7, §2.2）。

改訂版 L458 は「各演算子の出現頻度を均す」を選抜の規則として挙げている。実装計画 §2.2 は
**追加の処理なしでこれが満たされる**と主張している。24個のopが互いに対称なので、
全数を取る層では厳密に一様、抽出する層でも期待値が一様になるという理屈である。

その主張を実測で確認する。均す処理を後から足す必要があるかどうかが、ここで決まる。
"""

from collections import Counter

import pytest

from boku.semantics.enumeration import default_allocation, enumerate_asts
from boku.semantics.registry import OP_NAMES, OP_REGISTRY

ALLOC_30K = default_allocation(30_000)
ASTS_30K = enumerate_asts(ALLOC_30K, seed=0)

# 実測値（seed 0 / 1 / 7、target 30,000）は 2.07% / 3.08% / 2.09%。
# target 100,000 では 0.90% / 1.25% / 1.29% と、標本が増えるぶん小さくなる。
# 5% は実測の余裕を見た上限で、均す処理が要るほど偏ったら落ちる水準。
MAX_RELATIVE_DEVIATION = 0.05


def op_counts(asts) -> Counter[str]:
    """opの延べ出現回数。"""
    return Counter(op for ast in asts for op in ast.ops)


def test_difficulty_1_to_3_are_exactly_uniform() -> None:
    """全数を取る層では出現回数が**厳密に**等しい（実装計画 §2.2）。

    24個のopが対称であることの直接の帰結。ここが崩れたら列挙器か配分が壊れている。
    """
    counts = op_counts(ast for ast in ASTS_30K if ast.difficulty <= 3)
    assert set(counts) == set(OP_NAMES)
    assert len(set(counts.values())) == 1, dict(counts)
    # 24×1 + 552×2 + 12,144×3 = 37,560 延べ、24opで割って 1,565
    assert set(counts.values()) == {1_565}


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_op_frequency_is_near_uniform(seed: int) -> None:
    """既定配分の全体で、出現頻度が一様から一定範囲内（実装計画 §7）。

    偏りは difficulty 4 の抽出からしか生じない。標本が大きいので小さく収まる。
    """
    asts = ASTS_30K if seed == 0 else enumerate_asts(ALLOC_30K, seed=seed)
    counts = op_counts(asts)
    assert set(counts) == set(OP_NAMES), "出現しないopがある"

    expected = sum(counts.values()) / len(OP_NAMES)
    worst = max(abs(value - expected) / expected for value in counts.values())
    assert worst < MAX_RELATIVE_DEVIATION, (
        f"seed={seed} の最大相対偏差 {worst:.3%} が許容 {MAX_RELATIVE_DEVIATION:.0%} を超えた"
    )


def test_total_op_slots_matches_the_allocation() -> None:
    """opの延べ数が配分から計算できる値と一致する。"""
    expected = sum(
        difficulty * ALLOC_30K.for_difficulty(difficulty)
        for difficulty in range(1, 5)
    )
    assert expected == 24 * 1 + 552 * 2 + 12_144 * 3 + 17_280 * 4 == 106_680
    assert sum(op_counts(ASTS_30K).values()) == expected


def test_larger_target_reduces_the_deviation() -> None:
    """目標件数を増やすと偏りが小さくなる（抽出の標本が増えるため）。

    一様性が「構成的」であって偶然ではないことの傍証。
    """
    small = op_counts(ASTS_30K)
    large = op_counts(enumerate_asts(default_allocation(100_000), seed=0))

    def deviation(counts: Counter[str]) -> float:
        expected = sum(counts.values()) / len(OP_NAMES)
        return max(abs(v - expected) / expected for v in counts.values())

    assert deviation(large) < deviation(small)


def test_category_frequency_is_not_uniform() -> None:
    """**カテゴリ**の頻度は一様にならない（実装計画 §8 確認事項⑨）。

    L458 が求めているのは演算子単位の頻度であり、カテゴリのop数
    （filter 10 : map 8 : order 3 : slice 3）から一様にはならない。
    これを一様にしようとすると演算子単位の一様性が崩れるので、しない。
    """
    counts = Counter(
        OP_REGISTRY[op].category for ast in ASTS_30K for op in ast.ops
    )
    assert len(set(counts.values())) > 1, "カテゴリ頻度が一様になっている（op数の比と矛盾）"

    base = counts["order"] / 3
    for category, op_count in (("filter", 10), ("map", 8), ("order", 3), ("slice", 3)):
        ratio = counts[category] / (base * op_count)
        assert 0.95 < ratio < 1.05, (
            f"{category} の頻度がop数の比 {op_count} から外れている: {ratio:.3f}"
        )


def test_every_op_appears_in_every_difficulty_layer() -> None:
    """どの層でも24op全部が現れる（層ごとに欠けるopがない）。"""
    for difficulty in range(1, 5):
        counts = op_counts(a for a in ASTS_30K if a.difficulty == difficulty)
        assert set(counts) == set(OP_NAMES), f"difficulty {difficulty} に欠けるopがある"

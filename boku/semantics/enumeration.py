"""意味ASTの層化抽出（実装計画 §2.2）。

## なぜ層化するのか

意味AST空間 267,744種類のうち、**difficulty 4 だけで 95.2% を占める**。
1〜3操作は合計 12,720種類（4.8%）しかない。

```
difficulty 1        24  (  0.01%)
difficulty 2       552  (  0.21%)
difficulty 3    12,144  (  4.54%)
difficulty 4   255,024  ( 95.25%)
```

そのまま無作為に抽出すると4操作の問題が大半を占める。改訂版 L413 は
「難易度の分布を意図した形にするには、`difficulty`ごとの生成件数をあらかじめ決めて
層化抽出すること」と定めている。

## 既定の配分

L416-421 の配分例をそのまま既定にする。1〜3操作は**全数**、残りを difficulty 4 から抽出する。

```
difficulty 1        24 種類（全数）
difficulty 2       552 種類（全数）
difficulty 3    12,144 種類（全数）
difficulty 4    17,280 種類（255,024 種類から抽出）
合計            30,000 種類     1〜3操作 42% / 4操作 58%
```

## 難易度を均等にしない

改訂版 L457 が明示的に否定している。`difficulty` 1 は意味ASTが24種類しかなく、
1意味ASTあたり最大20例なら480レコード（約5万トークン）が上限である。4水準を均等に揃えると
訓練コーパス全体が約0.2M tokensに制限され、データ規模表の30〜100M tokensに二桁以上届かない。

## op出現頻度は自動的に均される

24個のopは互いに対称なので、全数を取る difficulty 1〜3 では**厳密に一様**、
difficulty 4 の一様抽出でも期待値が一様になる。改訂版 L458「各演算子の出現頻度を均す」が
追加の処理なしで満たされる（実装計画 §2.2）。`tests/test_op_frequency.py` で実測している。

ただし**カテゴリ**の頻度は一様にならない（filter 10 : map 8 : order 3 : slice 3）。
L458 が求めているのは演算子単位なので問題ないが、両方を `manifest.json` に出す
（実装計画 §8 確認事項⑨）。

## 空間を展開しない

difficulty 4 の抽出は `random.sample(range(255024), n)` で**番号の側だけ**を選び、
`unrank` で復元する。255,024件のリストを作らない。
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from boku.semantics.registry import MAX_OPS
from boku.semantics.semantic_ast import SemanticAST
from boku.semantics.unrank import COUNTS_BY_DIFFICULTY, TOTAL_COUNT, count, unrank

TARGET_MIN: Final[int] = 30_000
TARGET_MAX: Final[int] = 100_000
"""生成する意味ASTの目標件数の帯（改訂版 L397）。

**帯の外は拒否する**（実装計画 §2.2）。空間の上限（267,744）ではなく課題文の目安を
境界にするのは、帯の外の件数でコーパスを作れてしまうと、L424-437 の検算と
データ規模表の対応が黙って崩れるため。
"""

DEFAULT_TARGET: Final[int] = 30_000
"""既定の目標件数（改訂版 L416 の配分例）。"""


@dataclass(frozen=True, slots=True)
class Allocation:
    """difficulty ごとの生成件数（実装計画 §2.2）。"""

    counts: tuple[int, ...]
    """difficulty 1 から `MAX_OPS` までの件数。添字0が difficulty 1。"""

    def __post_init__(self) -> None:
        if not isinstance(self.counts, tuple):
            object.__setattr__(self, "counts", tuple(self.counts))

    @property
    def total(self) -> int:
        """合計件数。"""
        return sum(self.counts)

    def for_difficulty(self, difficulty: int) -> int:
        """指定した difficulty の件数。"""
        return self.counts[difficulty - 1]

    def is_exhaustive(self, difficulty: int) -> bool:
        """その difficulty を全数取るか。"""
        return self.for_difficulty(difficulty) == count(difficulty)

    def as_dict(self) -> dict[int, int]:
        """`manifest.json` に出す形。"""
        return {
            difficulty: self.counts[difficulty - 1]
            for difficulty in range(1, MAX_OPS + 1)
        }


def validate_target(target: int) -> None:
    """目標件数が改訂版 L397 の帯に収まることを確認する。

    **この検証は Hydra ではなくここで行う**（実装計画 §11 の依存の層）。
    設定ライブラリを差し替えても検証が消えないようにするため。

    Raises:
        ValueError: 帯の外のとき。
    """
    if not TARGET_MIN <= target <= TARGET_MAX:
        raise ValueError(
            f"target は {TARGET_MIN:,}〜{TARGET_MAX:,} の範囲（改訂版 L397）: target={target:,}"
        )


def default_allocation(target: int = DEFAULT_TARGET) -> Allocation:
    """既定の層化配分を作る（改訂版 L416-421）。

    difficulty 1 から `MAX_OPS - 1` までを全数取り、残りを `MAX_OPS` から抽出する。

    Raises:
        ValueError: `target` が帯の外か、空間に対して配分できないとき。

    Note:
        `MAX_OPS` を 3 に下げると空間が 12,720種類しかなくなり、帯を満たす `target` が
        存在せず必ずここで失敗する。**これは意図した挙動**であり、`MAX_OPS` を動かしたら
        L397 の目標件数の再検討が必要になることを実行時に気づかせるための safety net
        （実装計画 §2.2）。
    """
    validate_target(target)

    exhaustive = [count(difficulty) for difficulty in range(1, MAX_OPS)]
    remainder = target - sum(exhaustive)
    largest = count(MAX_OPS)

    if remainder < 0:
        raise ValueError(
            f"target={target:,} は difficulty 1〜{MAX_OPS - 1} の全数 "
            f"{sum(exhaustive):,} 件を下回る"
        )
    if remainder > largest:
        raise ValueError(
            f"target={target:,} は空間 {TOTAL_COUNT:,} 件を超える"
            f"（difficulty {MAX_OPS} に {remainder:,} 件必要だが {largest:,} 件しかない）"
        )
    return Allocation((*exhaustive, remainder))


def allocation_from_counts(counts: Sequence[int], target: int | None = None) -> Allocation:
    """明示指定された配分を検証して作る（実装計画 §2.2 の `alloc=[...]`）。

    Args:
        counts: difficulty 1 から `MAX_OPS` までの件数。
        target: 指定すると合計との一致を確認する。

    Raises:
        ValueError: 長さが合わない、負の件数、空間を超える、合計が `target` と違うとき。
    """
    if len(counts) != MAX_OPS:
        raise ValueError(
            f"配分は difficulty 1〜{MAX_OPS} の {MAX_OPS} 個で指定する: {list(counts)}"
        )
    for difficulty, value in enumerate(counts, start=1):
        if value < 0:
            raise ValueError(f"difficulty {difficulty} の件数が負: {value}")
        upper = count(difficulty)
        if value > upper:
            raise ValueError(
                f"difficulty {difficulty} は {upper:,} 件しかないのに {value:,} 件を要求している"
            )

    allocation = Allocation(tuple(counts))
    if target is not None and allocation.total != target:
        raise ValueError(
            f"配分の合計 {allocation.total:,} が target={target:,} と一致しない"
        )
    validate_target(allocation.total)
    return allocation


def _sample_indices(difficulty: int, wanted: int, seed: int) -> list[int]:
    """その difficulty から `wanted` 件の番号を選ぶ。

    全数なら並べるだけ、そうでなければ `random.sample` で一様に抽出する
    （実装計画 §2.2）。空間を展開しないので、difficulty 4 でもメモリを使わない。

    番号は**昇順に整列して返す**。`random.sample` の戻り順に依存しないので、
    同じ番号集合なら常に同じ並びになる。`ast_id` の採番（#8）が安定する。
    """
    upper = count(difficulty)
    if wanted == upper:
        return list(range(upper))
    # difficulty ごとに独立した乱数の名前空間を作る。ある層の件数を変えても
    # 他の層の抽出結果が動かないようにするため。
    rng = random.Random(seed * 100 + difficulty)
    return sorted(rng.sample(range(upper), wanted))


def enumerate_asts(allocation: Allocation, seed: int) -> list[SemanticAST]:
    """層化配分に従って意味ASTを列挙する。

    difficulty の昇順、各層の中では番号の昇順に並ぶ。同じ `allocation` と `seed` なら
    常に同じ並びになる（実装計画 §9 手順6 の再現性）。
    """
    asts: list[SemanticAST] = []
    for difficulty in range(1, MAX_OPS + 1):
        wanted = allocation.for_difficulty(difficulty)
        for index in _sample_indices(difficulty, wanted, seed):
            asts.append(SemanticAST(unrank(difficulty, index)))
    return asts


def space_summary() -> dict[str, object]:
    """意味AST空間の要約（`manifest.json` と報告用）。"""
    return {
        "total": TOTAL_COUNT,
        "by_difficulty": dict(COUNTS_BY_DIFFICULTY),
        "max_ops": MAX_OPS,
    }

"""意味AST空間の順位付け（実装計画 §2.2）。

意味AST空間は 267,744 種類あり、うち difficulty 4 だけで 255,024 種類を占める。
**この空間を配列に展開しない。** 代わりに通し番号とASTを相互変換できるようにして、
抽出は `random.sample(range(count(r)), n)` で番号の側だけを選ぶ。

```python
unrank(3, 0)        # -> ('abs', 'add_k', 'asc')   3op空間の0番目
rank(('abs', 'add_k', 'asc'))   # -> 0
count(4)            # -> 255024
```

## 下降階乗基数

「24個から r 個を順序付きで選ぶ」並びに、辞書順で 0 から通し番号を振る。
各桁の重み（基数）が一定でないのが普通の位取り記数法と違うところで、
先頭から桁を決めるたびに残りの選択肢が1つずつ減っていく。

difficulty 3（24個から3個）を例にとる。

```
1桁目を決めると、残り2桁の埋め方は 23 × 22 = 506 通り  ← 1桁目の重み
2桁目を決めると、残り1桁の埋め方は 22 通り              ← 2桁目の重み
3桁目の重みは 1

番号 1000 を復元する:
  1000 // 506 = 1 余り 494    未使用リストの 1 番目を取り出す
   494 //  22 = 22 余り 10    残った23個の 22 番目を取り出す
    10 //   1 = 10            残った22個の 10 番目を取り出す
```

重みは `perm(残りの個数 - 1, 残りの桁数 - 1)` で決まる。桁ごとに違い、右へ行くほど
小さくなるのでこう呼ぶ。番号とASTは1対1に対応する（`rank` が逆写像）。

## op出現頻度が構成的に一様になる

24個のopは互いに対称なので、ある difficulty の空間を全数とれば**各opの出現回数は厳密に等しい**。
difficulty 4 なら各opがちょうど 42,504 回（= 4 × 23×22×21）現れる。
そこから一様抽出しても期待値は一様のままである。

これにより改訂版 L458「各演算子の出現頻度を均す」が**追加の処理なしで満たされる**
（実装計画 §2.2）。`tests/test_unrank.py` で実際に数えて確認している。

## 並びへの依存

番号づけは `OP_NAMES`（辞書順、`registry.py`）の並びを基準にする。並びを変えると
同じ番号が別のASTを指すため、`registry.py` 側で並びを固定してある。
"""

from math import perm
from typing import Final

from boku.semantics.registry import MAX_OPS, N_OPS, OP_NAMES

_BLOCK_SIZES: Final[dict[int, tuple[int, ...]]] = {
    r: tuple(perm(N_OPS - position - 1, r - position - 1) for position in range(r))
    for r in range(1, MAX_OPS + 1)
}
"""桁の重みの表。`_BLOCK_SIZES[r][position]` が difficulty `r` の `position` 桁目の重み。

毎回 `perm()` を呼ばずに済ませるために import 時に作る。表は最大 4×4 なので小さい。
"""

COUNTS_BY_DIFFICULTY: Final[dict[int, int]] = {
    r: perm(N_OPS, r) for r in range(1, MAX_OPS + 1)
}
"""difficulty ごとの空間の大きさ（改訂版 L405-411）。24 / 552 / 12,144 / 255,024。"""

TOTAL_COUNT: Final[int] = sum(COUNTS_BY_DIFFICULTY.values())
"""意味AST空間の全体（改訂版 L410）。267,744。"""


def count(difficulty: int) -> int:
    """difficulty `r` の意味ASTの個数を返す。

    24個から `r` 個を順序付きで、重複なく選ぶ場合の数（改訂版 L403-411）。

    Raises:
        ValueError: `difficulty` が 1〜`MAX_OPS` の外のとき。
    """
    _check_difficulty(difficulty)
    return COUNTS_BY_DIFFICULTY[difficulty]


def unrank(difficulty: int, index: int) -> tuple[str, ...]:
    """difficulty `r` の空間の `index` 番目の意味ASTを返す（0始まり、辞書順）。

    空間を展開せずに直接復元するので、difficulty 4 の 255,024 種類から抽出する場合も
    メモリを使わない。

    Args:
        difficulty: 操作数。1〜`MAX_OPS`。
        index: 通し番号。0 以上 `count(difficulty)` 未満。

    Returns:
        op名のタプル。同一opは含まれない。

    Raises:
        ValueError: `difficulty` が範囲外のとき。
        IndexError: `index` が範囲外のとき。
    """
    _check_difficulty(difficulty)
    upper = COUNTS_BY_DIFFICULTY[difficulty]
    if not 0 <= index < upper:
        raise IndexError(
            f"index は 0〜{upper - 1} の範囲（difficulty={difficulty}）: index={index}"
        )

    remaining = list(OP_NAMES)
    blocks = _BLOCK_SIZES[difficulty]
    chosen: list[str] = []
    for position in range(difficulty):
        block = blocks[position]
        choice, index = divmod(index, block)
        chosen.append(remaining.pop(choice))
    return tuple(chosen)


def rank(ops: tuple[str, ...]) -> int:
    """`unrank` の逆写像。意味ASTから通し番号を返す。

    Args:
        ops: op名のタプル。長さ 1〜`MAX_OPS`、同一opの重複なし、既知のop名のみ。

    Raises:
        ValueError: 長さが範囲外、未知のop名、または同一opの重複があるとき。

    Note:
        構造検証は `validate.py` の担当だが、この関数は番号づけの前提が崩れると
        黙って誤った番号を返してしまうため、ここでも弾く。誤った番号は
        「別のASTを指す番号」になり、コーパスの取り違えとして静かに伝播する。
    """
    difficulty = len(ops)
    _check_difficulty(difficulty)

    remaining = list(OP_NAMES)
    blocks = _BLOCK_SIZES[difficulty]
    index = 0
    for position, name in enumerate(ops):
        try:
            choice = remaining.index(name)
        except ValueError:
            if name in OP_NAMES:
                raise ValueError(
                    f"同一opの重複: {name!r}（改訂版 L111）"
                ) from None
            raise ValueError(f"未知のop名: {name!r}（L113-157 の表にない）") from None
        index += choice * blocks[position]
        remaining.pop(choice)
    return index


def _check_difficulty(difficulty: int) -> None:
    """difficulty が 1〜`MAX_OPS` に収まることを確認する（改訂版 L111）。"""
    if not 1 <= difficulty <= MAX_OPS:
        raise ValueError(
            f"difficulty は 1〜{MAX_OPS} の整数（改訂版 L111）: difficulty={difficulty}"
        )

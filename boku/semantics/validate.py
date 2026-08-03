"""意味ASTの構造検証（実装計画 §2.7）。

検証するのは次の3項目**だけ**である。

1. `difficulty` が 1〜`MAX_OPS`（改訂版 L111「1〜4個」）
2. 同一opの重複がない（L111「同一の操作を2回以上使用しない」）
3. 未知のop名がない（L113-157 の表にある名前だけ）

## 代数的な書き換えをしない

次のような等価則は**手書きしない**（実装計画 §2.7）。

```
[even, odd]     → 常に空
[negate, abs]   → [abs] と同じ
[square, abs]   → [square] と同じ
[asc, desc]     → [desc] と同じ
```

手書きの代数則は、間違えると**正解データそのものを汚染する**。しかも間違いは静かで、
モデルの学習結果を見るまで気づけない。だから縮退の検出は評価に任せる。
`behavior_hash`（実装計画 §2.5）が固定入力集合での出力列を比べるので、
意味が同じASTは自動的に同じ指紋になる。

**参照インタプリタが意味の唯一の権威であり続ける。**

構造的な枝刈りも同じ理由で書けない。順序が自由（L297）なので、たとえば
「並べ替えは最後のものだけが効く」は**偽**である。`[asc, take_first, desc]` の `asc` は
`take_first` が何を取るかを決めているので効いている。filter の並べ替えも行わない
（順序が意味を持つ表現で並べ替えると情報が壊れる）。

したがって、常に空になるASTも恒等になるASTも**検証は通す**。それらは
`always_empty` / `is_identity` として記録し、除去するかどうかの判断は選抜段に委ねる
（実装計画 §2.5、§8 確認事項⑦）。
"""

from collections import Counter

from boku.semantics.registry import MAX_OPS, OP_REGISTRY
from boku.semantics.semantic_ast import SemanticAST


class ValidationError(ValueError):
    """意味ASTが構造検証に通らなかった。"""


def problems(ast: SemanticAST) -> list[str]:
    """構造上の問題を**すべて**列挙する。問題がなければ空リスト。

    最初の1件で止めないのは、コーパス構築時に「何件がどの理由で落ちたか」を集計するためである
    （実装計画 §9 の「構造検証通過 ＝ 全件」の確認）。1件だけ返すと理由の分布が取れない。
    """
    found: list[str] = []

    if ast.difficulty < 1:
        found.append(f"操作数が0（1〜{MAX_OPS}であること、改訂版 L111）")
    elif ast.difficulty > MAX_OPS:
        found.append(
            f"操作数が{ast.difficulty}（1〜{MAX_OPS}であること、改訂版 L111）"
        )

    duplicated = sorted(
        name for name, count in Counter(ast.ops).items() if count > 1
    )
    if duplicated:
        found.append(
            f"同一opの重複: {', '.join(duplicated)}（L111「同一の操作を2回以上使用しない」）"
        )

    unknown = [name for name in ast.ops if name not in OP_REGISTRY]
    if unknown:
        found.append(f"未知のop名: {', '.join(unknown)}（L113-157 の表にない）")

    return found


def is_valid(ast: SemanticAST) -> bool:
    """構造検証を通るか。"""
    return not problems(ast)


def validate(ast: SemanticAST) -> None:
    """構造検証を行い、通らなければ `ValidationError` を送出する。

    Raises:
        ValidationError: 問題が1件以上あるとき。メッセージに全件を並べる。
    """
    found = problems(ast)
    if found:
        raise ValidationError(f"{ast}: " + " / ".join(found))

"""コード生成器のインタフェース宣言（実装計画 §1「今回作らないもの」、§10）。

**宣言のみ。実装しない。**意味AST層の下流にあたり、Phase 1 後半の担当である。

## なぜ今のうちに宣言するのか

改訂版 L281-286 は、各意味ASTから**独立した二つのプログラム**を作ることを求めている。

- 正解を計算する参照インタプリタ（`boku.interp`、実装済み）
- 学習対象となるPythonコードを出力するコード生成器（この層、未実装）

そして両者の出力をランダムテストで比較し、**コード生成器自身のバグを検出する**。
この差分テストが意味AST層の設計（レジストリに意味を置かない、実装計画 §2.8）の理由なので、
受け口の形だけ先に決めておく。

## 実装するときの受け入れ条件

生成した全てのコードを実行し、参照インタプリタと同じ結果になる場合だけ採用する（L352）。

```python
# パラメータ版
assert eval_solve(emit(ast, None, style))(xs, k) == run(ast.ops, xs, k)

# リテラル版（binding = v）。改訂版 L269 の等価性がここに効く
assert eval_solve(emit(ast, v, style))(xs, k) == run(ast.ops, xs, v)
```

リテラル版は引数 `k` を参照しないが、**シグネチャは `solve(xs, k)` のまま保つ**（L279）。
"""

from typing import Protocol

from boku.semantics.semantic_ast import Binding, SemanticAST

CodeStyle = str
"""コード形式の識別子。具体的な語彙はコード生成器の実装時に決める。

改訂版 L344-350 は、同じ意味ASTから複数の等価コードを作るために次を変えることを求めている。

- 内包表記と通常の `for` ループ
- 一時変数の有無
- 変数名の変更
- 条件式の順序変更
- `reverse=True` と逆順操作
- 1行の `return` と複数行形式
- コメントおよび型注釈の有無

型注釈の有無を等価な表現として扱えるのは、L98 が固定するのを
「関数名が `solve`」「位置引数が `xs`, `k` の2個」の二点に限っているため。
"""


class CodeGenerator(Protocol):
    """意味ASTからPythonコードを生成する。"""

    def emit(self, ast: SemanticAST, binding: Binding, style: CodeStyle) -> str:
        """`solve(xs, k)` の実装を1つ返す。

        Args:
            ast: 意味AST。定数は含まない（改訂版 L256）。
            binding: `None` ならパラメータ版、`int` なら**全スロットを**その値に具体化した
                リテラル版（実装計画 §2.4）。混在は型として表現できない。
            style: コード形式。

        Returns:
            `def solve(xs, k):` で始まるPythonソース。
        """
        ...

"""意味ASTの評価（実装計画 §5）。

`run(ast, xs, k)` が意味ASTを左から順に適用する。これが正解の定義であり、
`behavior_hash`（実装計画 §2.5）も生成コードの検証（改訂版 L352）もこの出力を基準にする。
"""

from collections.abc import Sequence

from boku.interp.ops import OP_IMPLS
from boku.limits import K_MAX, K_MIN


def run(ast: Sequence[str], xs: Sequence[int], k: int) -> list[int]:
    """意味AST `ast` を入力 `(xs, k)` に適用した結果を返す。

    操作は**列の順に**適用する。順序は意味を持つ（改訂版 L297-302）。
    `[asc, take_first]` と `[take_first, asc]` は別の関数である。

    引数 `xs` は複製してから使うため、**呼び出し元のリストは変更されない**
    （実装計画 §5、`tests/test_no_mutation.py`）。各opも新しいリストを返すので
    複製は二重の保険にあたるが、この関数の契約として明示しておく。

    `k` は各opにそのまま渡す。ASTは定数を持たないため（改訂版 L256）、
    `k` を解決する処理は要らない（実装計画 §5）。

    リテラルに具体化したコードの検証にもこの関数を使う。リテラル `v` に一様具体化した版は
    `run(ast, xs, v)` と一致する（L269、実装計画 §2.4 の一様具体化の制約）。

    Args:
        ast: op名の列。空列を渡すと恒等（`xs` の複製）を返す。
        xs: 入力リスト。長さは L102 の 0〜20、要素は L103 の −100〜100 を想定する。
        k: L104 の 1〜10 の整数。

    Returns:
        評価結果の新しいリスト。要素は L103 の範囲を超えてよい（L105）。

    Raises:
        ValueError: `k` が L104 の範囲外のとき。
        KeyError: `ast` に未知のop名が含まれるとき。

    Note:
        **構造検証はここでは行わない。** 操作数が 1〜`MAX_OPS` か、同一opの重複がないかは
        `boku.semantics.validate` の担当である（実装計画 §2.7）。この関数は「渡された列を
        順に適用する」ことだけに責任を持つ。役割を混ぜると、権威である評価器に検証の都合が
        混ざる。
    """
    if not (K_MIN <= k <= K_MAX):
        raise ValueError(f"k は {K_MIN}〜{K_MAX} の整数（改訂版 L104）: k={k}")

    current = list(xs)
    for op_name in ast:
        impl = OP_IMPLS.get(op_name)
        if impl is None:
            raise KeyError(f"未知のop名: {op_name!r}")
        current = impl(current, k)
    return current

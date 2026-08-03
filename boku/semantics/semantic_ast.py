"""意味ASTのデータ構造（実装計画 §2.1, §5）。

意味ASTは**op名の順序付き列だけ**を表す。`k` の値などの定数は含めない（改訂版 L256）。
定数のバリエーションは後段のサンプル展開が吸収する。この定義があるから「意味AST単位での分割」
（L465）が漏洩防止として機能する。

```python
SemanticAST(("ge", "double", "asc"))   # L251 の例と同形
```

## この型が持つもの・持たないもの

持つのは**op列から一意に決まる値だけ**である。`difficulty` や `op_set` や
`uniform_literal_domain` は op列とレジストリがあれば計算できるので、ここで導出する。

持たないのは次の二種類。

- **評価しないと決まらない値**：`behavior_hash` / `always_empty` / `is_identity`。
  参照インタプリタと固定入力集合が要るので `fingerprint.py`（実装計画 §2.5）の担当
- **コーパスに載せるときに決まる値**：`ast_id` / `created_at` / 各 version。
  採番と由来の記録なので `corpus.py`（実装計画 §4）の担当

**構造の妥当性も検証しない。** 操作数が1〜4か、同一opの重複がないか、未知のop名がないかは
`validate.py` の担当である（実装計画 §2.7）。この型は不正な列でも構築できる。そうしておかないと
検証器そのものをテストできない。
"""

import json
from dataclasses import dataclass
from typing import Any, Final, Self

from boku.semantics.registry import CATEGORY_ORDER, LITERAL_MAX, LITERAL_MIN, OP_REGISTRY

SCHEMA_VERSION: Final[int] = 1
"""レコード形式の版（実装計画 §4）。`schema.json` と対応する。

フィールドの追加・削除・意味の変更で上げる。
"""


@dataclass(frozen=True, slots=True)
class BindingSlot:
    """`k` を参照するopの位置と、そこに入れられるリテラルの値域（実装計画 §2.4）。

    **具体値は持たない。** 意味ASTは定数を含まないため（改訂版 L256）、ここに置くのは
    「展開層が選べる範囲」だけである。実際にどの値を入れるかは展開層（今回スコープ外）が決める。
    """

    index: int
    """AST内での位置（0始まり）。同じopでも位置が違えば別スロット。"""

    op: str
    """op名。"""

    literal_domain: tuple[int, ...]
    """このスロット単独で使えるリテラル（改訂版 L269-277）。

    複数スロットを持つASTでは、実際に使えるのは
    `SemanticAST.uniform_literal_domain`（全スロットの共通部分）に狭まる。
    """

    def to_dict(self) -> dict[str, Any]:
        """実装計画 §4 のレコード形式に合わせた辞書。"""
        return {
            "index": self.index,
            "op": self.op,
            "literal_domain": list(self.literal_domain),
        }


@dataclass(frozen=True, slots=True)
class SemanticAST:
    """op名の順序付き列。

    適用順序は自由であり、同じopの集合でも順序が違えば別の意味ASTとして扱う
    （改訂版 L297）。したがって列であって集合ではない。
    """

    ops: tuple[str, ...]
    """op名の列。左から順に適用する。"""

    def __post_init__(self) -> None:
        """リストやジェネレータで渡されてもタプルに正規化する。

        凍結データクラスなので `object.__setattr__` で書き込む。ハッシュ可能性を保つために
        タプルであることが必要（`semantic_hash` の算出や集合演算で使う）。
        """
        if not isinstance(self.ops, tuple):
            object.__setattr__(self, "ops", tuple(self.ops))

    # ---- op列から決まる値 ----

    @property
    def difficulty(self) -> int:
        """組み合わせた操作の個数（改訂版 L386）。層化抽出の層になる（L413）。"""
        return len(self.ops)

    @property
    def op_set(self) -> tuple[str, ...]:
        """順序を落としてソートしたop集合。**予約ペアの引き当てキー**（実装計画 §4）。

        L472 の予約ペアで L485 の「個々の操作は学習したが組合せは見ていない」状況を作るには、
        `[even, desc]` と `[desc, even]` の両方を除外する必要がある。だから順序非依存の
        キーが要る（実装計画 §8 確認事項⑧）。

        同一opは重複しない前提（L111）なので、単に並べ替えるだけでよい。
        """
        return tuple(sorted(self.ops))

    @property
    def categories(self) -> tuple[str, ...]:
        """各opのカテゴリを**AST順で**並べたもの（実装計画 §4）。

        重複し得る（`["even", "odd"]` なら `("filter", "filter")`）。
        """
        return tuple(OP_REGISTRY[name].category for name in self.ops)

    @property
    def canonical_order(self) -> bool:
        """カテゴリ順（抽出→変換→並べ替え→切り出し）に従っているか。

        **記録するだけで、列挙は制限しない**（実装計画 §2.2）。改訂版 L297 が順序を自由と
        定めているため、これは分析とアブレーションの材料である。順序を固定すると意味AST空間が
        12,950 種類に縮み、L397 の目標件数に届かなくなる（`CHANGES.md` 11-3）。

        判定はカテゴリの並びが非減少かどうか。同カテゴリ内の順序は問わない。
        """
        ranks = [CATEGORY_ORDER.index(category) for category in self.categories]
        return all(a <= b for a, b in zip(ranks, ranks[1:]))

    @property
    def uses_k(self) -> bool:
        """`k` を参照するopを1つ以上含むか。"""
        return any(OP_REGISTRY[name].uses_k for name in self.ops)

    @property
    def binding_slots(self) -> tuple[BindingSlot, ...]:
        """`k` 参照opの位置と値域をAST順で並べたもの（実装計画 §2.4）。"""
        return tuple(
            BindingSlot(
                index=index,
                op=name,
                literal_domain=OP_REGISTRY[name].literal_domain,
            )
            for index, name in enumerate(self.ops)
            if OP_REGISTRY[name].uses_k
        )

    @property
    def uniform_literal_domain(self) -> tuple[int, ...]:
        """全スロットを**同一の値**に具体化する場合に使えるリテラル（実装計画 §2.4）。

        各スロットの値域の共通部分である。`k` 参照opが無ければ空タプル。

        共通部分でなければならないのは、改訂版 L269 の検証等価性が「全スロットを同じ値に
        具体化した場合」にしか成立しないためである。スロットごとに別の値を入れると、
        どの `k` での参照インタプリタ評価とも一致せず、正誤を判定できない。

        `k` 参照スロットを2個以上持つASTは空間の 55.4% を占めるので、これは例外ではなく既定の経路。
        共通部分が空になるASTは存在せず、最小でも7値が残る（除外がすべて値域の下限側にあり、
        最大の除外集合が `mul_k` の {1, 2, 3} であるため）。
        """
        slots = self.binding_slots
        if not slots:
            return ()
        allowed = set(range(LITERAL_MIN, LITERAL_MAX + 1))
        for slot in slots:
            allowed &= set(slot.literal_domain)
        return tuple(sorted(allowed))

    # ---- 直列化 ----

    def canonical_json(self) -> str:
        """`semantic_hash` の入力になる正準表現（実装計画 §2.5）。

        op列だけから決まる。**`created_at` などの由来情報は入れない**（実装計画 §4）。
        入れると同一seedでの再実行が別のハッシュになり、再現性の確認ができなくなる。

        派生値（`difficulty` など）も入れない。op列から一意に決まるので情報が増えず、
        レジストリの改訂で値が変わるとハッシュまで動いてしまうため。
        """
        return json.dumps(list(self.ops), ensure_ascii=False, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        """実装計画 §4 のレコード形式のうち、**op列から決まる部分**を返す。

        `semantic_hash` や `ast_id` は含まない。それぞれ `fingerprint.py` と `corpus.py` が
        後から足す。
        """
        return {
            "semantic_ast": list(self.ops),
            "difficulty": self.difficulty,
            "categories": list(self.categories),
            "op_set": list(self.op_set),
            "canonical_order": self.canonical_order,
            "binding_slots": [slot.to_dict() for slot in self.binding_slots],
            "uniform_literal_domain": list(self.uniform_literal_domain),
            "uses_k": self.uses_k,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """`to_dict()` の逆。**`semantic_ast` だけを読み、派生値は再計算する。**

        派生値を入力として信用しないのは、それらがop列とレジストリから一意に決まるからである。
        レジストリを改訂した後で古いレコードを読み込んだ場合、記録された派生値は古い。
        再計算すれば常に現在のレジストリと整合する。

        ただし辞書に派生値が入っていて、それが再計算した値と食い違う場合は `ValueError` にする。
        黙って捨てると、古いコーパスや壊れたレコードを読んでいることに気づけない。

        Raises:
            KeyError: `semantic_ast` が無いとき。
            ValueError: 派生値が再計算した値と食い違うとき。
        """
        ast = cls(tuple(data["semantic_ast"]))

        expected = ast.to_dict()
        for key, value in data.items():
            if key not in expected or key == "semantic_ast":
                continue
            if value != expected[key]:
                raise ValueError(
                    f"派生値 {key!r} がop列と矛盾する: "
                    f"レコード={value!r} 再計算={expected[key]!r}"
                )
        return ast

    def is_valid_binding(self, binding: "Binding") -> bool:
        """バインディングが §2.4 の一様具体化の制約を満たすか。

        許すのは2形態だけである。

        1. `None`（パラメータ版）：全スロットを `k` のまま残す
        2. `uniform_literal_domain` の要素（リテラル版）：全スロットを同じ値に具体化する

        スロットごとに別の値を入れる形は、そもそも `Binding` の型として表現できない。
        表現できてしまうと、展開層が改訂版 L269 の検証等価性を壊すコードを作れてしまう。
        """
        if binding is None:
            return True
        return binding in self.uniform_literal_domain

    def __str__(self) -> str:
        """`[ge, double, asc]` の形。ログと失敗メッセージ用。"""
        return "[" + ", ".join(self.ops) + "]"


Binding = int | None
"""リテラル具体化のバインディング（実装計画 §2.4 のフック）。

- `None` … パラメータ版。全スロットが `k` を参照したまま。任意の `k` で検証できる
- `int` … リテラル版。**全スロットを同じ値に具体化する。**検証は `k = その値` で行う

**スロットごとに別の値を持てない形にしてある。**改訂版 L269 の検証等価性が成立するのは
一様に具体化した場合だけであり、混在させるとどの `k` での参照インタプリタ評価とも一致しなくなる。
型で表現できないようにすることが、展開層（今回スコープ外）への最も強い申し送りになる。

値の選び方は `SemanticAST.uniform_literal_domain`（各スロット値域の共通部分）に従う。
`SemanticAST.is_valid_binding` が検査する。
"""

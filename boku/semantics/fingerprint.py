"""意味ASTの指紋（実装計画 §2.5, §4）。

2種類のハッシュを持つ。**役割が違う**ので混同しないこと。

| | 何から作るか | 何に使うか |
| --- | --- | --- |
| `semantic_hash` | op列の正準JSON | 分割の単位（改訂版 L465）、漏洩検査**第1項**（L520） |
| `behavior_hash` | 固定入力集合に対する出力列 | 漏洩検査**第5項**（L524） |

## なぜ `behavior_hash` が要るのか

操作の適用順序を自由にした（L297）ことの直接の帰結として、**可換な操作対では異なる意味ASTが
完全に同じ関数を表す**（L526）。

```
[even, positive] と [positive, even]   フィルタ同士は可換
[even, desc]     と [desc, even]       フィルタと整列も可換
[double, triple] と [triple, double]   どちらも ×6
[square, abs]    と [square]           二乗は常に非負なので abs が恒等
```

これらは `semantic_hash` が異なるので漏洩検査の第1項を通過し、生成コードも文字列としては
違うので第4項も通過してしまう。**しかしモデルにとっては同一の課題である。**訓練とテストに
分かれると、通常テストの数値が実際より高く出る（L534）。`behavior_hash` はこれを捕まえる。

## 構築時に除去しない

改訂版 L536 は「重複が見つかった場合は、**テスト側のレコードを除外する**」と定めている。
つまり処理する場所は**分割後の漏洩検査**であって、コーパス構築時ではない。
構築時に前倒しすると、L416-421 の層化配分の「全数」（difficulty 2 の 552 など）が崩れ、
L397 の目標件数も意図せず減る。

したがってこの層は**算出して記録するだけ**にする。衝突の除去は分割スクリプト（今回スコープ外）の
仕事である（実装計画 §2.5、§8 確認事項⑥）。

`always_empty` / `is_identity` も同じ扱いで、記録して件数を報告し、除去するかどうかの判断は
選抜段に委ねる（§8 確認事項⑦）。

## 由来情報を入力に混ぜない

`created_at` などの由来情報は**どちらのハッシュにも入れない**（実装計画 §4）。
入れると同一seedでの再実行が別のハッシュになり、再現性の確認（§9 手順6）ができなくなる。
この関数群がそもそも時刻を引数に取らないことで、構造的に保証している。
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from boku.probes.behavior_probes import ProbeInput, probe_outputs
from boku.semantics.semantic_ast import SemanticAST


def _sha256(text: str) -> str:
    """UTF-8 でエンコードした文字列の SHA-256（16進64桁）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def semantic_hash(ast: SemanticAST) -> str:
    """op列の正準JSONのハッシュ。

    **分割の単位**である（改訂版 L465）。順序が違えば別の値になる（L297）ので、
    `[asc, take_first]` と `[take_first, asc]` は別のASTとして扱われる。

    定数を含まない（L256）ため、同じ操作列なら `k` の値が違っても同じ値になる。
    これが「意味AST単位での分割」を漏洩防止として機能させている。
    """
    return _sha256(ast.canonical_json())


def behavior_outputs(
    ast: SemanticAST, probes: Sequence[ProbeInput]
) -> tuple[tuple[int, ...], ...]:
    """固定入力集合に対する参照インタプリタの出力列。

    `behavior_hash` の材料であり、`always_empty` / `is_identity` の判定にも使う。
    3つを別々に計算すると同じ評価を3回することになるので、`fingerprint()` はこれを
    一度だけ呼んで使い回す。
    """
    return probe_outputs(ast.ops, probes)


def behavior_hash_of(outputs: Sequence[Sequence[int]]) -> str:
    """出力列からハッシュを作る（改訂版 L536）。

    入力集合の**順序に依存する**。だから入力集合を凍結する（実装計画 §2.5）。
    出力列だけから作り、op列も由来情報も混ぜない。混ぜると「意味ASTが違っても関数として
    同一なら同じ値になる」（L388）という性質が壊れ、可換対を検出できなくなる。
    """
    payload = json.dumps(
        [list(output) for output in outputs],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _sha256(payload)


def behavior_hash(ast: SemanticAST, probes: Sequence[ProbeInput]) -> str:
    """固定入力集合に対する出力列のハッシュ（改訂版 L388, L536）。"""
    return behavior_hash_of(behavior_outputs(ast, probes))


def is_always_empty(
    outputs: Sequence[Sequence[int]],
) -> bool:
    """固定入力集合の全入力で出力が空になるか（`[even, odd]` など）。

    除去はしない。件数を報告して選抜段の判断材料にする（実装計画 §2.5）。
    """
    return all(len(output) == 0 for output in outputs)


def is_identity_over(
    probes: Sequence[ProbeInput], outputs: Sequence[Sequence[int]]
) -> bool:
    """固定入力集合の全入力で入力と同じ出力になるか。

    「恒等かどうか」は入力集合の上での判定であって、数学的な恒等性の証明ではない。
    識別力のある入力集合（実装計画 §2.5）を使っている前提で、実用上の目安として記録する。
    """
    return all(
        tuple(output) == xs for (xs, _), output in zip(probes, outputs, strict=True)
    )


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """1つの意味ASTの指紋一式（実装計画 §4 のレコードの一部）。"""

    semantic_hash: str
    behavior_hash: str
    always_empty: bool
    is_identity: bool

    def to_dict(self) -> dict[str, Any]:
        """実装計画 §4 のレコード形式に合わせた辞書。"""
        return {
            "semantic_hash": self.semantic_hash,
            "behavior_hash": self.behavior_hash,
            "always_empty": self.always_empty,
            "is_identity": self.is_identity,
        }


def fingerprint(ast: SemanticAST, probes: Sequence[ProbeInput]) -> Fingerprint:
    """指紋を一度の評価でまとめて作る。

    **時刻を受け取らない。** 由来情報がハッシュに混ざらないことを、引数の形で保証している
    （実装計画 §4、`tests/test_hash_excludes_timestamp.py`）。
    """
    outputs = behavior_outputs(ast, probes)
    return Fingerprint(
        semantic_hash=semantic_hash(ast),
        behavior_hash=behavior_hash_of(outputs),
        always_empty=is_always_empty(outputs),
        is_identity=is_identity_over(probes, outputs),
    )


def group_by_behavior(
    asts: Sequence[SemanticAST], probes: Sequence[ProbeInput]
) -> dict[str, list[SemanticAST]]:
    """`behavior_hash` ごとにASTをまとめる。

    衝突グループの報告に使う（実装計画 §9 の期待出力「異なり数と最大衝突グループ長」）。
    除去はしない。
    """
    groups: dict[str, list[SemanticAST]] = {}
    for ast in asts:
        groups.setdefault(behavior_hash(ast, probes), []).append(ast)
    return groups

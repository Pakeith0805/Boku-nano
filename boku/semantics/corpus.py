"""ASTコーパスの読み書き（実装計画 §4）。

`data/ast/asts.jsonl`（1行1レコード）と `data/ast/manifest.json`（1回の生成の要約）を扱う。

## レコードは3つの層の合成

| 層 | 出どころ | 何を足すか |
| --- | --- | --- |
| op列から決まる値 | `SemanticAST.to_dict()` | `semantic_ast` `difficulty` `binding_slots` など |
| 評価しないと決まらない値 | `Fingerprint.to_dict()` | `semantic_hash` `behavior_hash` `always_empty` `is_identity` |
| コーパスに載せて決まる値 | この層 | `ast_id` と由来3項目、各 version |

## 由来3項目（改訂版 L795-808）

- **`source`** — AST層では**常に `"rule"`**。改訂版 L57「正解の意味構造、コード、テストは
  ルールベースで作成し、教師モデルは自然言語表現を増やす役割に限定する」および L53
  「開発支援AIに個々の学習サンプルを直接書かせる」の禁止により、教師由来・開発支援AI由来の
  意味ASTは存在してはいけない。テストで常時ガードにする（実装計画 §4）
- **`created_at`** — **各ハッシュと `ast_id` の入力に含めない。**含めると同一seedでの再実行が
  別物になり、実装計画 §9 手順6 の再現性確認ができなくなる
- **`generator_version`** — 単一定数 `BOKU_GENERATOR_VERSION` を手で上げる。
  参照インタプリタを直したときも上げること（`behavior_hash` が変わるため）

## `ast_id` は実行をまたぐキーではない

配分や `target` や `seed` を変えると振り直される連番である。実行をまたいで同一性を見るときは
`semantic_hash` を使う（分割の単位でもある、改訂版 L465）。
"""

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from boku import BOKU_GENERATOR_VERSION
from boku.probes.behavior_probes import ProbeInput
from boku.semantics.enumeration import Allocation
from boku.semantics.fingerprint import (
    Fingerprint,
    behavior_hash_of,
    behavior_outputs,
    is_always_empty,
    is_identity_over,
    semantic_hash,
)
from boku.semantics.registry import MAX_OPS, OP_REGISTRY, REGISTRY_VERSION
from boku.semantics.semantic_ast import SCHEMA_VERSION, SemanticAST
from boku.semantics.unrank import TOTAL_COUNT

SOURCE_RULE: Final[str] = "rule"
"""AST層の `source` の唯一の値（改訂版 L53, L57）。"""

AST_ID_DIGITS: Final[int] = 6
"""`ast_id` の桁数。`schema.json` の `^ast-[0-9]{6}$` と対応する。

目標件数の上限 100,000（改訂版 L397）を6桁で表せる。
"""


def utc_now_rfc3339() -> str:
    """現在時刻を RFC 3339（UTC、秒精度）で返す。

    秒精度に落とすのは、レコードの読みやすさと差分の取りやすさのため。
    **この値はハッシュにも `ast_id` にも入らない。**
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_ast_id(number: int) -> str:
    """連番から `ast_id` を作る（1始まり、実装計画 §4 の `ast-000001`）。"""
    if number < 1:
        raise ValueError(f"ast_id の連番は1以上: {number}")
    return f"ast-{number:0{AST_ID_DIGITS}d}"


@dataclass(frozen=True, slots=True)
class RecordMeta:
    """全レコードに共通で載る由来と版（実装計画 §4）。"""

    created_at: str
    generator_version: str = BOKU_GENERATOR_VERSION
    registry_version: str = REGISTRY_VERSION
    probe_set_version: str = "v1"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """レコードに載せる形。`source` は常に `"rule"`。"""
        return {
            "source": SOURCE_RULE,
            "created_at": self.created_at,
            "generator_version": self.generator_version,
            "schema_version": self.schema_version,
            "registry_version": self.registry_version,
            "probe_set_version": self.probe_set_version,
        }


def build_record(
    ast: SemanticAST, fingerprint: Fingerprint, number: int, meta: RecordMeta
) -> dict[str, Any]:
    """1件のレコードを組み立てる（実装計画 §4）。"""
    return {
        "ast_id": format_ast_id(number),
        **ast.to_dict(),
        **fingerprint.to_dict(),
        **meta.to_dict(),
    }


def build_records(
    asts: Sequence[SemanticAST], probes: Sequence[ProbeInput], meta: RecordMeta
) -> tuple[list[dict[str, Any]], int]:
    """全レコードと、出力値の絶対値の最大桁数を返す。

    指紋の算出はコーパス構築で最も重い処理（AST数 × 入力数の評価）なので、
    **1つのASTにつき評価は一度だけ**にして、そこから指紋と桁数の両方を得る。

    Returns:
        `(レコード列, 出力値の絶対値の最大桁数)`。桁数は Phase 2 のトークナイザ設計への
        申し送りとして `manifest.json` に載せる（実装計画 §6）。
        改訂版 L105 は出力が −100〜100 を超えることを許しているため、実測が要る。
    """
    records: list[dict[str, Any]] = []
    max_digits = 0
    for number, ast in enumerate(asts, start=1):
        outputs = behavior_outputs(ast, probes)
        fingerprint = Fingerprint(
            semantic_hash=semantic_hash(ast),
            behavior_hash=behavior_hash_of(outputs),
            always_empty=is_always_empty(outputs),
            is_identity=is_identity_over(probes, outputs),
        )
        for output in outputs:
            for value in output:
                max_digits = max(max_digits, len(str(abs(value))))
        records.append(build_record(ast, fingerprint, number, meta))
    return records, max_digits


def write_records(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """JSONL で書き出す（1行1レコード）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            )


def read_records(path: Path) -> list[dict[str, Any]]:
    """JSONL を読み戻す。順序を保つ。"""
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def records_to_asts(records: Iterable[dict[str, Any]]) -> list[SemanticAST]:
    """レコードから意味ASTを復元する。

    `SemanticAST.from_dict` が派生値の整合も見るので、レジストリを改訂した後に
    古いコーパスを読むと `ValueError` になる（実装計画 §3 の設計）。
    """
    return [SemanticAST.from_dict(record) for record in records]


def build_manifest(
    records: Sequence[dict[str, Any]],
    *,
    allocation: Allocation,
    target: int,
    seed: int,
    probe_count: int,
    max_output_digits: int,
    meta: RecordMeta,
    drop_behavior_duplicates: bool = False,
) -> dict[str, Any]:
    """1回の生成の要約（実装計画 §4, §9 の期待される出力）。

    レコードから導ける値はレコードから数える。二重に持つと食い違う余地ができるため、
    `max_output_digits` だけを外から受け取る（出力そのものはレコードに載らない）。

    **`manifest.json` は MLflow に載せても残す**（実装計画 §11）。MLflow のストアは
    ツールの都合で移動・消去され得るが、こちらはコーパスと同じ場所に置かれた由来の記録であり、
    改訂版 L795-808 が求めているのはそちら。
    """
    actual_by_difficulty = Counter(record["difficulty"] for record in records)
    op_frequency = Counter(op for record in records for op in record["semantic_ast"])
    category_frequency = Counter(
        OP_REGISTRY[op].category for record in records for op in record["semantic_ast"]
    )
    slot_distribution = Counter(len(record["binding_slots"]) for record in records)

    behavior_groups = Counter(record["behavior_hash"] for record in records)
    collision_groups = {
        digest: size for digest, size in behavior_groups.items() if size > 1
    }

    uniform_sizes = [
        len(record["uniform_literal_domain"])
        for record in records
        if record["uses_k"]
    ]
    canonical = sum(1 for record in records if record["canonical_order"])

    return {
        "created_at": meta.created_at,
        "generator_version": meta.generator_version,
        "registry_version": meta.registry_version,
        "probe_set_version": meta.probe_set_version,
        "schema_version": meta.schema_version,
        "seed": seed,
        "target": target,
        "max_ops": MAX_OPS,
        "space_total": TOTAL_COUNT,
        "probe_count": probe_count,
        "drop_behavior_duplicates": drop_behavior_duplicates,
        "record_count": len(records),
        "allocation": {
            "planned": {str(k): v for k, v in allocation.as_dict().items()},
            "actual": {
                str(difficulty): actual_by_difficulty.get(difficulty, 0)
                for difficulty in range(1, MAX_OPS + 1)
            },
        },
        "op_frequency": dict(sorted(op_frequency.items())),
        "category_frequency": dict(sorted(category_frequency.items())),
        "canonical_order_ratio": round(canonical / len(records), 6) if records else 0.0,
        "k_slot_distribution": {
            str(slots): slot_distribution.get(slots, 0)
            for slots in range(MAX_OPS + 1)
        },
        "uniform_literal_domain_min": min(uniform_sizes) if uniform_sizes else 0,
        "behavior_hash": {
            "distinct": len(behavior_groups),
            "collision_groups": len(collision_groups),
            "largest_group": max(behavior_groups.values()) if behavior_groups else 0,
            "asts_in_collisions": sum(collision_groups.values()),
        },
        "always_empty_count": sum(1 for r in records if r["always_empty"]),
        "is_identity_count": sum(1 for r in records if r["is_identity"]),
        "max_output_abs_digits": max_output_digits,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """`manifest.json` を書き出す（人が読むので整形する）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path) -> dict[str, Any]:
    """`manifest.json` を読む。"""
    return json.loads(path.read_text(encoding="utf-8"))

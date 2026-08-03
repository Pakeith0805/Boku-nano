"""コーパスの読み書きの検査（実装計画 §7 の #8、§4）。

`asts.jsonl` と `manifest.json` の往復、`ast_id` の採番、由来3項目を固定する。

レコードは3つの層の合成なので、合成の過程でフィールドが落ちたり上書きされたりしないことが
主な関心事になる。落ちても静かに動いてしまう（JSONは足りないキーを教えてくれない）。
"""

import json
from pathlib import Path

import pytest

from boku import BOKU_GENERATOR_VERSION
from boku.probes.behavior_probes import default_probe_set_path, load_probe_set
from boku.semantics.corpus import (
    AST_ID_DIGITS,
    SOURCE_RULE,
    RecordMeta,
    build_manifest,
    build_records,
    format_ast_id,
    read_manifest,
    read_records,
    records_to_asts,
    utc_now_rfc3339,
    write_manifest,
    write_records,
)
from boku.semantics.enumeration import Allocation, default_allocation, enumerate_asts
from boku.semantics.registry import MAX_OPS, REGISTRY_VERSION
from boku.semantics.semantic_ast import SCHEMA_VERSION, SemanticAST
from boku.semantics.unrank import TOTAL_COUNT

ROOT = Path(__file__).resolve().parents[1]
PROBES = load_probe_set(default_probe_set_path(ROOT, "v1"))
META = RecordMeta(created_at="2026-07-30T12:00:00Z")

# 小さな標本で回す。全件（30,000）は #9 のスクリプトの担当。
SAMPLE_ASTS = [
    SemanticAST(ops)
    for ops in (
        ("ge", "double", "asc"),
        ("even",),
        ("even", "desc"),
        ("desc", "even"),
        ("even", "odd"),
        ("square", "abs"),
        ("square",),
        ("mul_k", "square"),
        ("negate", "abs", "square"),
        ("even", "add_k", "desc", "take_first"),
    )
]
RECORDS, MAX_DIGITS = build_records(SAMPLE_ASTS, PROBES, META)


def test_ast_id_format() -> None:
    """`ast_id` が `ast-000001` の形（`schema.json` のパターンと対応）。"""
    assert format_ast_id(1) == "ast-000001"
    assert format_ast_id(30_000) == "ast-030000"
    assert format_ast_id(100_000) == "ast-100000"
    assert AST_ID_DIGITS == 6


def test_ast_id_rejects_zero_and_negative() -> None:
    """連番は1始まり。"""
    for number in (0, -1):
        with pytest.raises(ValueError):
            format_ast_id(number)


def test_ast_id_is_sequential_from_one() -> None:
    """採番が1から連番で振られる。"""
    assert [record["ast_id"] for record in RECORDS] == [
        format_ast_id(number) for number in range(1, len(SAMPLE_ASTS) + 1)
    ]


def test_record_has_every_field_in_the_schema() -> None:
    """レコードが `schema.json` の必須フィールドを過不足なく持つ。

    3つの層を合成しているので、どこかが落ちても静かに動く。ここで止める。
    """
    schema = json.loads(
        (ROOT / "boku" / "semantics" / "schema.json").read_text(encoding="utf-8")
    )
    required = set(schema["required"])
    declared = set(schema["properties"])
    for record in RECORDS:
        assert set(record) == required, set(record) ^ required
        assert set(record) <= declared


def test_provenance_fields() -> None:
    """由来3項目と各 version（実装計画 §4）。"""
    for record in RECORDS:
        assert record["source"] == SOURCE_RULE
        assert record["created_at"] == "2026-07-30T12:00:00Z"
        assert record["generator_version"] == BOKU_GENERATOR_VERSION
        assert record["registry_version"] == REGISTRY_VERSION
        assert record["schema_version"] == SCHEMA_VERSION
        assert record["probe_set_version"] == "v1"


def test_source_is_always_rule() -> None:
    """`source` が常に `"rule"`（改訂版 L53, L57）。

    教師モデル由来・開発支援AI由来の意味ASTは存在してはいけない。常時ガード。
    """
    assert SOURCE_RULE == "rule"
    assert {record["source"] for record in RECORDS} == {"rule"}


def test_created_at_does_not_affect_hashes_or_ast_id() -> None:
    """`created_at` を差し替えてもハッシュと `ast_id` が変わらない（実装計画 §4, §7）。

    含めると同一seedでの再実行が別物になり、§9 手順6 の再現性確認ができなくなる。
    """
    other = RecordMeta(created_at="1999-01-01T00:00:00Z")
    other_records, _ = build_records(SAMPLE_ASTS, PROBES, other)

    for left, right in zip(RECORDS, other_records, strict=True):
        assert left["created_at"] != right["created_at"]
        assert left["ast_id"] == right["ast_id"]
        assert left["semantic_hash"] == right["semantic_hash"]
        assert left["behavior_hash"] == right["behavior_hash"]


def test_records_roundtrip_through_jsonl(tmp_path: Path) -> None:
    """`asts.jsonl` に書いて読み戻すと完全に一致する。"""
    path = tmp_path / "asts.jsonl"
    write_records(path, RECORDS)
    assert read_records(path) == RECORDS


def test_records_roundtrip_to_semantic_asts(tmp_path: Path) -> None:
    """レコードから意味ASTを復元できる。

    `SemanticAST.from_dict` が派生値の整合も見るので、`to_dict` と `from_dict` が
    食い違っていればここで落ちる。
    """
    path = tmp_path / "asts.jsonl"
    write_records(path, RECORDS)
    assert records_to_asts(read_records(path)) == SAMPLE_ASTS


def test_jsonl_is_one_record_per_line(tmp_path: Path) -> None:
    """1行1レコードで、各行が単独でJSONとして読める。"""
    path = tmp_path / "asts.jsonl"
    write_records(path, RECORDS)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(RECORDS)
    assert all(json.loads(line)["ast_id"] for line in lines)


def test_known_collision_shares_behavior_hash_in_records() -> None:
    """レコードの上でも既知の縮退が同じ `behavior_hash` になる。

    指紋の層が正しくレコードに載っていることの確認。
    """
    by_ops = {tuple(r["semantic_ast"]): r for r in RECORDS}
    assert (
        by_ops[("even", "desc")]["behavior_hash"]
        == by_ops[("desc", "even")]["behavior_hash"]
    )
    assert (
        by_ops[("square", "abs")]["behavior_hash"]
        == by_ops[("square",)]["behavior_hash"]
    )
    assert (
        by_ops[("even", "desc")]["semantic_hash"]
        != by_ops[("desc", "even")]["semantic_hash"]
    )


def test_always_empty_is_recorded_not_removed() -> None:
    """常に空になるASTも除去せずレコードに残る（実装計画 §2.5、§8 確認事項⑦）。"""
    by_ops = {tuple(r["semantic_ast"]): r for r in RECORDS}
    assert by_ops[("even", "odd")]["always_empty"] is True
    assert by_ops[("even",)]["always_empty"] is False


def test_max_output_digits_is_measured() -> None:
    """出力値の絶対値の最大桁数が取れている（実装計画 §6）。

    改訂版 L105 は出力が −100〜100 を超えることを許している。`mul_k` や `square` で
    大きくなるので、Phase 2 のトークナイザ設計（語彙4,096）への申し送りとして実測する。
    """
    assert MAX_DIGITS >= 4, "±100 を超える出力が観測されていない"


# ---- manifest ----

ALLOCATION = Allocation((3, 4, 2, 1))
MANIFEST = build_manifest(
    RECORDS,
    allocation=ALLOCATION,
    target=30_000,
    seed=0,
    probe_count=len(PROBES),
    max_output_digits=MAX_DIGITS,
    meta=META,
)


def test_manifest_contains_every_required_item() -> None:
    """実装計画 §4 が列挙する項目が揃っている。"""
    for key in (
        "seed",
        "target",
        "max_ops",
        "allocation",
        "op_frequency",
        "category_frequency",
        "canonical_order_ratio",
        "k_slot_distribution",
        "uniform_literal_domain_min",
        "behavior_hash",
        "always_empty_count",
        "is_identity_count",
        "max_output_abs_digits",
        "generator_version",
        "registry_version",
        "probe_set_version",
        "schema_version",
    ):
        assert key in MANIFEST, key

    for key in ("distinct", "collision_groups", "largest_group", "asts_in_collisions"):
        assert key in MANIFEST["behavior_hash"], key


def test_manifest_counts_match_the_records() -> None:
    """要約がレコードと食い違わない。"""
    assert MANIFEST["record_count"] == len(RECORDS)
    assert sum(MANIFEST["op_frequency"].values()) == sum(
        len(r["semantic_ast"]) for r in RECORDS
    )
    assert MANIFEST["always_empty_count"] == sum(
        1 for r in RECORDS if r["always_empty"]
    )
    assert MANIFEST["max_ops"] == MAX_OPS
    assert MANIFEST["space_total"] == TOTAL_COUNT
    assert MANIFEST["probe_count"] == len(PROBES)


def test_manifest_reports_behavior_collisions() -> None:
    """衝突の報告が実態と合う（標本に既知の縮退を2組入れてある）。"""
    digests = [r["behavior_hash"] for r in RECORDS]
    assert MANIFEST["behavior_hash"]["distinct"] == len(set(digests))
    assert MANIFEST["behavior_hash"]["collision_groups"] >= 2
    assert MANIFEST["behavior_hash"]["largest_group"] >= 2
    assert MANIFEST["behavior_hash"]["asts_in_collisions"] >= 4


def test_manifest_roundtrip(tmp_path: Path) -> None:
    """`manifest.json` に書いて読み戻すと一致する。"""
    path = tmp_path / "manifest.json"
    write_manifest(path, MANIFEST)
    assert read_manifest(path) == MANIFEST


def test_manifest_is_human_readable(tmp_path: Path) -> None:
    """整形して書く（人が読む記録なので）。"""
    path = tmp_path / "manifest.json"
    write_manifest(path, MANIFEST)
    text = path.read_text(encoding="utf-8")
    assert "\n  " in text, "整形されていない"
    assert text.endswith("\n")


def test_manifest_allocation_records_planned_and_actual() -> None:
    """配分は計画値と実件数の両方を残す。

    層化抽出が意図どおりに効いたかは、両方を並べないと分からない。
    """
    assert MANIFEST["allocation"]["planned"] == {"1": 3, "2": 4, "3": 2, "4": 1}
    assert MANIFEST["allocation"]["actual"]["1"] == sum(
        1 for r in RECORDS if r["difficulty"] == 1
    )


def test_manifest_is_json_serializable_with_stdlib() -> None:
    """標準の `json` だけで書ける（§11 の依存の層）。"""
    assert json.loads(json.dumps(MANIFEST)) == MANIFEST


def test_utc_now_is_rfc3339() -> None:
    """`created_at` の形式（`schema.json` の `format: date-time`）。"""
    now = utc_now_rfc3339()
    assert now.endswith("Z")
    assert len(now) == len("2026-07-30T12:00:00Z")


def test_real_allocation_shape_is_accepted() -> None:
    """本番の配分（24 / 552 / 12,144 / 17,280）でも manifest を作れる。"""
    manifest = build_manifest(
        RECORDS,
        allocation=default_allocation(30_000),
        target=30_000,
        seed=0,
        probe_count=len(PROBES),
        max_output_digits=MAX_DIGITS,
        meta=META,
    )
    assert manifest["allocation"]["planned"] == {
        "1": 24,
        "2": 552,
        "3": 12_144,
        "4": 17_280,
    }


def test_enumerated_asts_produce_records() -> None:
    """列挙器（#7）の出力をそのままレコードにできる。

    層をまたいだ接続の確認。小さな配分で通す。
    """
    asts = enumerate_asts(Allocation((24, 5, 0, 0)), seed=0)
    records, _ = build_records(asts, PROBES[:10], META)
    assert len(records) == 29
    assert records_to_asts(records) == asts

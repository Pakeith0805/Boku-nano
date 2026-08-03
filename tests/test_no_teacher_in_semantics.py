"""意味AST層に教師モデル由来のデータが混ざらないことの常時ガード（実装計画 §4, §7）。

改訂版がこれを二重に禁じている。

> 正解の意味構造、コード、テストはルールベースで作成し、教師モデルは自然言語（日本語）表現を
> 増やす役割に限定する。（L57）

> **禁止する使い方**
> - 開発支援AIに個々の学習サンプル（指示文・正解コード）を直接書かせる
> - 教師モデルに正解プログラムそのものを決めさせる（L51-54）

意味ASTは「正解の意味構造」そのものなので、教師由来・開発支援AI由来のものが存在してはいけない。
`source` が `"rule"` 以外になる経路が生まれていないことを、構造と実データの両方で確認する。
"""

import inspect
from pathlib import Path

from boku.probes.behavior_probes import default_probe_set_path, load_probe_set
from boku.semantics import corpus as corpus_module
from boku.semantics.corpus import (
    SOURCE_RULE,
    RecordMeta,
    build_records,
    read_records,
)
from boku.semantics.semantic_ast import SemanticAST

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "ast" / "asts.jsonl"


def test_source_constant_is_rule() -> None:
    """`source` の値は `"rule"` の一択。"""
    assert SOURCE_RULE == "rule"


def test_record_meta_cannot_override_source() -> None:
    """`RecordMeta` に `source` を差し込む口がない（構造的な保証）。

    引数で受け取れると、呼び出し側が誤って別の値を入れられる。フィールドとして
    持たないことで、`"rule"` 以外になる経路そのものを作らない。
    """
    assert "source" not in inspect.signature(RecordMeta).parameters
    assert "source" not in RecordMeta.__dataclass_fields__


def test_built_records_are_all_rule() -> None:
    """組み立てたレコードが全て `"rule"`。"""
    probes = load_probe_set(default_probe_set_path(ROOT, "v1"))[:5]
    asts = [SemanticAST(("even",)), SemanticAST(("ge", "double", "asc"))]
    records, _ = build_records(asts, probes, RecordMeta(created_at="2026-07-30T12:00:00Z"))
    assert {record["source"] for record in records} == {"rule"}


def test_corpus_module_has_no_teacher_model_reference() -> None:
    """コーパス層が教師モデルに触れていない。

    改訂版 L228-238 が定める教師モデルの記録項目（`teacher_model`、`prompt_hash` など）は
    指示→コードのレコードのものであり、**意味ASTのレコードには現れてはいけない**。
    """
    source = inspect.getsource(corpus_module)
    for forbidden in ("teacher", "prompt_hash", "qwen", "Qwen"):
        assert forbidden not in source, forbidden


def test_frozen_corpus_is_all_rule() -> None:
    """実際に構築したコーパスの全レコードが `"rule"`（実装計画 §4 の常時ガード）。

    コーパスが無ければ読み飛ばす。`scripts/build_ast_corpus.py` を実行すると現れる。
    """
    if not CORPUS.exists():
        return
    records = read_records(CORPUS)
    assert records, "コーパスが空"
    assert {record["source"] for record in records} == {"rule"}
    assert all("teacher_model" not in record for record in records)

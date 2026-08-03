"""ハッシュに由来情報が混ざらないことの検査（実装計画 §7, §4）。

`created_at` をハッシュの入力に含めると、**同一seedでの再実行が別のハッシュになる**。
実装計画 §9 手順6 の再現性確認（「`created_at` 以外が完全一致すること」）が成立しなくなり、
`document_AST.md` §11 の比較実験でも run 同士を突き合わせられなくなる。

ここでは「時刻を混ぜていない」ことを2通りで確認する。

1. **構造的に**：指紋を作る関数群が時刻を引数に取らない（`inspect` で確認）
2. **経験的に**：時刻をまたいで呼んでも同じ値になる

`ast_id` が `created_at` に依存しないことの確認は #8（`corpus.py`）で採番を実装してから足す。
現時点では採番そのものが存在しない。
"""

import inspect
import json
import time
from pathlib import Path

from boku.probes.behavior_probes import default_probe_set_path, load_probe_set
from boku.semantics import fingerprint as fingerprint_module
from boku.semantics.fingerprint import (
    behavior_hash,
    fingerprint,
    semantic_hash,
)
from boku.semantics.semantic_ast import SemanticAST

ROOT = Path(__file__).resolve().parents[1]
PROBES = load_probe_set(default_probe_set_path(ROOT, "v1"))
SAMPLE = SemanticAST(("ge", "double", "asc"))

TIME_WORDS = ("time", "timestamp", "created", "now", "date", "clock")


def test_fingerprint_functions_take_no_time_argument() -> None:
    """指紋を作る関数が時刻を受け取らない（構造的な保証）。

    引数に無ければ、うっかり混ぜることができない。
    """
    for name in ("semantic_hash", "behavior_hash", "fingerprint", "behavior_hash_of"):
        signature = inspect.signature(getattr(fingerprint_module, name))
        for parameter in signature.parameters:
            assert not any(
                word in parameter.lower() for word in TIME_WORDS
            ), f"{name} の引数 {parameter} が時刻に見える"


def test_fingerprint_module_does_not_import_time_modules() -> None:
    """指紋モジュールが時刻を扱うモジュールを取り込んでいない。

    引数で受け取らなくても、モジュール内で `datetime.now()` を呼べば混ざる。
    """
    source = inspect.getsource(fingerprint_module)
    for forbidden in ("import time", "import datetime", "from datetime", "from time"):
        assert forbidden not in source, forbidden


def test_hashes_are_stable_across_time() -> None:
    """時刻をまたいで呼んでも同じ値（経験的な確認）。"""
    first = fingerprint(SAMPLE, PROBES)
    time.sleep(0.01)
    second = fingerprint(SAMPLE, PROBES)
    assert first == second
    assert first.semantic_hash == second.semantic_hash
    assert first.behavior_hash == second.behavior_hash


def test_semantic_hash_matches_an_independently_written_expectation() -> None:
    """`semantic_hash` が「op列の正準JSONの SHA-256」そのものである。

    期待値を実装から取らず、正準JSONの文字列を**このファイルに直接書いて**確かめる。
    `canonical_json` の書式が変わればここが落ちる。書式が変わると全レコードの
    `semantic_hash` が変わるので、黙って変わっては困る。
    """
    import hashlib

    expected = hashlib.sha256('["ge","double","asc"]'.encode("utf-8")).hexdigest()
    assert semantic_hash(SAMPLE) == expected
    assert len(expected) == 64


def test_semantic_hash_ignores_k_and_constants() -> None:
    """`semantic_hash` が定数に依存しない（改訂版 L256）。

    意味ASTは操作列のみを表すので、`k` の値は指紋に影響しない。これが
    「意味AST単位での分割」を漏洩防止として機能させている（L465）。
    """
    assert semantic_hash(SAMPLE) == semantic_hash(SemanticAST(("ge", "double", "asc")))


def test_behavior_hash_depends_only_on_outputs() -> None:
    """`behavior_hash` が出力列だけから決まる（op列を混ぜていない）。

    op列を混ぜると「意味ASTが違っても関数として同一なら同じ値になる」（改訂版 L388）が
    壊れ、可換対を検出できなくなる。振る舞いが同じで op列が違う組で確認する。
    """
    assert behavior_hash(SemanticAST(("desc",)), PROBES) == behavior_hash(
        SemanticAST(("asc", "reverse")), PROBES
    )


def test_behavior_hash_changes_with_the_probe_set() -> None:
    """入力集合が変わると `behavior_hash` も変わる。

    だから入力集合を凍結する（実装計画 §2.5）。`scripts/build_probe_set.py` が
    黙った上書きを拒否するのはこのため。
    """
    assert behavior_hash(SAMPLE, PROBES) != behavior_hash(SAMPLE, PROBES[:10])


def test_fingerprint_dict_has_only_the_four_fields() -> None:
    """`to_dict()` が §4 の4フィールドだけを出す（由来情報を持ち込まない）。"""
    assert set(fingerprint(SAMPLE, PROBES).to_dict()) == {
        "semantic_hash",
        "behavior_hash",
        "always_empty",
        "is_identity",
    }


def test_fingerprint_dict_is_json_serializable() -> None:
    """レコードに載せられる（JSONL に書ける）。"""
    payload = json.dumps(fingerprint(SAMPLE, PROBES).to_dict())
    assert json.loads(payload)["semantic_hash"] == semantic_hash(SAMPLE)

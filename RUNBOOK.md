# RUNBOOK — `document_AST.md` の実装手順

`document_AST.md`（Phase 1 前半の実装計画）を**どの順に実装するか**だけを書いた手順書。
設計の根拠は `document_AST.md` に、仕様の根拠は改訂版の課題文にある。ここでは順番と検証だけを扱う。

## 前提（一度だけ）

```powershell
uv python install 3.12   # 済
uv sync                  # 済。.venv と uv.lock を作る
```

## 常用コマンド

```powershell
uv run pytest -q                     # 全テスト
uv run pytest tests/test_unrank.py -q  # 単体
uv run python --version              # 3.12.13 であること
```

`uv run` を通さない `python` は msys2 の 3.14 を掴むので使わない。

## 実装の順序

**依存関係の順に並べてある。**上から順に進める。1チャンクごとに止めて確認を取る。

| # | 作るもの | 完了条件（テスト） | 依存 |
| --: | --- | --- | --- |
| 1 ✅ | `semantics/registry.py` | `test_registry_conformance.py` `test_literal_domains.py` | — |
| 2 ✅ | `interp/ops.py` `interp/run.py` `limits.py` | `test_interp_ops.py` `test_interp_differential.py` `test_no_mutation.py` `test_golden_example.py` `test_limits.py` ＋ #1 のskip解除 | #1 |
| 3 ✅ | `semantics/semantic_ast.py` `validate.py` `schema.json` | `test_ast_roundtrip.py` `test_validate.py` `test_uniform_literal_domain.py` `test_literal_binding_equivalence.py` | #1 #2 |
| 4 ✅ | `semantics/unrank.py` | `test_unrank.py` | #1 |
| 5 ✅ | `probes/behavior_probes.py` `scripts/build_probe_set.py` `conf/probe_set.yaml` | `test_probe_discriminates.py` | #2 |
| 6 ✅ | `semantics/fingerprint.py` | `test_known_collisions.py` `test_hash_excludes_timestamp.py` | #2 #3 #5 |
| 7 ✅ | `semantics/enumeration.py` | `test_stratified_alloc.py` `test_op_frequency.py` | #3 #4 |
| 8 ✅ | `semantics/corpus.py` | `test_corpus_roundtrip.py`（`asts.jsonl` / `manifest.json`） | #3 #6 |
| 9 | `scripts/build_ast_corpus.py` `conf/*.yaml` ＋ MLflow | `test_no_teacher_in_semantics.py` `test_core_has_no_external_deps.py` | 全部 |
| 10 | `codegen/` `ja/` の Protocol、`docs/*.md` | 宣言のみ（実装しない） | — |

### 順序の理由

- **#2 を早くに置く。** 参照インタプリタは意味の唯一の権威（§2.7）だが、それを検証する差分ランダム
  テストの相手（コード生成器）は今回スコープ外である。したがって `test_interp_ops.py` の手書き期待値が
  実質唯一のガードになる。ここが弱いと下流すべてが静かに汚染される
- **#5 は #2 の後。** 固定入力集合は参照インタプリタで作るため、インタプリタが固まってからでないと
  凍結できない（`probe_set_version` を打ち直すことになる）
- **#9 が最後。** Hydra と MLflow を触るのはこの層だけ（§11）。`boku/` 側は素の関数のままにする

## 各チャンクの手順

1. 実装する
2. `uv run pytest -q` が通ることを確認する
3. 計画の数値に関わるチャンク（#4 #6 #7）は、テストとは別に独立検算を回して
   `document_AST.md` の数値と一致することを確認する
4. **止めて、確認を取る。** 計画に書かれていなかった判断があれば列挙して報告する
5. 承認後、`README.md` の「実装状況」に追記する

## 通し検証（#9 完了後）

`document_AST.md` §9 の手順1〜7 をそのまま実行する。期待される出力もそこに書いてある。

```powershell
uv run pytest -q
uv run python -m scripts.build_probe_set probe_set.version=v1
uv run python -m scripts.build_ast_corpus target=30000 seed=0
```

配分が **24 / 552 / 12,144 / 17,280**（合計 30,000）になることが最初の関門。

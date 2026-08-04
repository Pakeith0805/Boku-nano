# RUNBOOK — 実装手順

実装計画を**どの順に実装するか**だけを書いた手順書。
設計の根拠は各実装計画に、仕様の根拠は改訂版の課題文にある。ここでは順番と検証だけを扱う。

| 範囲 | 実装計画 | 手順 |
| --- | --- | --- |
| Phase 1 前半（意味AST層・参照インタプリタ） | `document_AST.md` | #1〜#10（完了） |
| Phase 1 後半(1)（分割・漏洩検査） | `document_SPLIT.md` | #11〜#13 |
| Phase 1 後半(2)（展開・生成器・選抜） | `document_EXPAND.md` | #14〜#20 |

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
| 9 ✅ | `scripts/build_ast_corpus.py` `conf/config.yaml` ＋ MLflow | `test_no_teacher_in_semantics.py` `test_core_has_no_external_deps.py` | 全部 |
| 10 ✅ | `codegen/` `ja/` の Protocol、`docs/*.md` | `test_protocol_hooks.py`（宣言のみ、実装しない） | — |

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

**#1〜#10 完了（2026-08-03）。** Phase 1 前半は終わり。

## 通し検証（#9 完了後）

`document_AST.md` §9 の手順1〜7 をそのまま実行する。期待される出力もそこに書いてある。

```powershell
uv run pytest -q
uv run python -m scripts.build_probe_set probe_set.version=v1
uv run python -m scripts.build_ast_corpus target=30000 seed=0
```

配分が **24 / 552 / 12,144 / 17,280**（合計 30,000）になることが最初の関門。

---

# Phase 1 後半

## 着手前の判断（2026-08-04 決着済み）

**`target` を 30,000 → 45,000 に上げた**（`conf/config.yaml`）。改訂版 L424-437 の検算は分割を
無視して全数に20例を掛けているが、L465 は分割してから展開すると定めているため、
`target=30,000` では訓練集合がデータ規模の3つの帯すべてを下回っていた。45,000 は
3 epoch で3帯すべてを満たす最小値である。副作用として difficulty 4 の比率が 57.6% → 71.7% に
上がるが、これは受け入れて記録する（`document_EXPAND.md` §1）。

コーパスは再生成済み（45,000件）。以降の件数はすべてこの前提。

## 実装の順序

**依存関係の順に並べてある。**上から順に、1チャンクごとに止めて確認を取る。

| # | 作るもの | 完了条件（テスト） | 依存 | 計画 |
| --: | --- | --- | --- | --- |
| 11 | `boku/split/reserve.py` `partition.py` | `test_reserve_pairs.py` `test_partition_strata.py` | #8 | SPLIT §2.2-2.4 |
| 12 | `boku/split/leakage.py`（第1・3・5項） | `test_leakage_checks.py` | #11 | SPLIT §2.6 |
| 13 | `boku/split/manifest.py` `scripts/build_splits.py` `conf/split.yaml` | `test_split_manifest_roundtrip.py` `test_split_reproducible.py` | #12 | SPLIT §3 §6 |
| 14 | `boku/expand/binding.py` | `test_binding_expansion.py` | #13 | EXPAND §2.1 |
| 15 | `boku/codegen/emit.py` `styles.py` | `test_codegen_differential.py` `test_codegen_independence.py` `test_code_styles.py` | #14 | EXPAND §2.3-2.5 |
| 16 | `scripts/teacher/generate_phrases.py` ＋ 承認CLI | 承認済み辞書が op あたり15表現以上 | — | EXPAND §2.7 §2.8 |
| 17 | `boku/ja/render.py` `phrasebook.py` | `test_ja_order_markers.py` `test_ja_no_duplicate_instruction.py` `test_phrasebook_split.py` | #16 | EXPAND §2.6 §2.2 |
| 18 | 解説文レコード（生成＋承認） | `test_dataset_schema.py` | #16 | EXPAND §2.9 |
| 19 | `boku/verify/checks.py` `select.py` | `test_verify_checks.py` | #15 #17 | EXPAND §2.11 §2.12 |
| 20 | `scripts/build_dataset.py` ＋ 漏洩検査 段2 | `test_leakage_stage2.py` | 全部 | EXPAND §2.12 §5 |

### 順序の理由

- **#11〜#13 が先。** L465 が「日本語文やコードを生成する前に分割する」と定めている。
  逆順にすると同じ問題の表記違いが訓練とテストに入る
- **#15 を #17 より前に置く。** コード生成器は参照インタプリタとの差分テストで正しさを測れるが、
  日本語生成器を機械的に検証する相手はいない。**先に測れる方を固める**
- **#16 に人間が入る。** 教師モデルの生成と承認は自動化しない（L288-295）。
  ここだけリードタイムが読めないので、#14 #15 と並行して着手してよい
- **#16 の着手条件は解消済み**（2026-08-04、再起動で `nvidia-smi` が復旧）。
  GPU は RTX 5090・32,607 MiB・compute capability 12.0（sm_120）。
  ただし**推論スタックが sm_120 に対応しているかを、辞書生成の本番前に1プロンプトで確かめる**
  （AWQ カーネルは世代依存。EXPAND §2.7）。GPU は他プロセスと共有している
- **#20 が最後。** Hydra と MLflow を触るのはこの層だけ

### 各チャンクの手順（前半と同じ）

1. 実装する
2. `uv run pytest -q` が通ることを確認する
3. 計画の数値に関わるチャンク（#11 #12 #14 #19）は、テストとは別に独立検算を回して
   実装計画の数値と一致することを確認する
4. **止めて、確認を取る。** 計画に書かれていなかった判断があれば列挙して報告する
5. 承認後、`README.md` の「実装状況」に追記する

コミットは**人間がする。**

# Boku-nano

日本語の指示から限定的なPython関数（`solve(xs, k)`）を生成する Small Language Model を、
データ生成から評価までフルスクラッチで作る実習プロジェクト。

現在は **Phase 1 前半：意味AST層 ＋ 参照インタプリタ** を実装中。

## ドキュメントの地図

読む順序が決まっている。**推測で埋めず、この順に参照する。**

| ファイル | 位置づけ |
| --- | --- |
| `芦原・倉林研究室_..._改訂版.md` | **唯一の正となる仕様書。** 迷ったらまずここ |
| `document_AST.md` | Phase 1 前半の実装計画。改訂版を工程ごとに詳細化したもの |
| `RUNBOOK.md` | `document_AST.md` を**どの順に実装するか**の手順書 |
| `README.md`（本ファイル） | 全体の入口と**実装状況の記録** |
| `CHANGES.md` | 原版→改訂版の変更履歴。「なぜその値か」を調べるときだけ読む |
| `芦原・倉林研究室_..._の開発.md`（原版） | 旧版。内部矛盾を含むため**仕様として読まない** |

改訂版の記述を、実装計画やコードが上書きしてはいけない。食い違いを見つけたら報告する。

## 環境

Python **3.12**（`.python-version` で固定）、パッケージ管理は **uv**。

```powershell
uv python install 3.12
uv sync
uv run pytest -q
```

設定管理は **Hydra**、実験管理は **MLflow**（`document_AST.md` §11）。
依存の層を分けており、**意味の権威（参照インタプリタ・レジストリ）には外部ライブラリを入れない。**

| 層 | 許す依存 |
| --- | --- |
| `boku/semantics/` `boku/interp/` `boku/probes/` | 標準ライブラリのみ |
| `scripts/` | ＋ `hydra-core`、`mlflow` |
| `tests/` | ＋ `pytest` |

## ディレクトリ

```
boku/
  semantics/   意味ASTのデータ構造・検証・列挙・指紋
  interp/      参照インタプリタ（意味の唯一の権威）
  probes/      behavior_hash 用の固定入力集合
conf/          Hydra の設定
scripts/       実行の入口（Hydra と MLflow を触るのはここだけ）
tests/         pytest
```

---

## 実装状況

進んだぶんだけ追記する。各チャンクは `RUNBOOK.md` の番号に対応する。

### #1 op レジストリ — 完了（2026-07-30）

24種類の操作のメタデータ。全モジュールが依存する土台。

**作ったもの**

| ファイル | 内容 |
| --- | --- |
| `boku/semantics/registry.py` | `OpSpec`、`OP_REGISTRY`（24op）、`MAX_OPS`、リテラル値域、`OP_NAMES` |
| `tests/test_registry_conformance.py` | 改訂版 L113-157 の表との照合 16件 |
| `tests/test_literal_domains.py` | `document_AST.md` §2.4 の値域表との照合 14件 |
| `boku/__init__.py` | `BOKU_GENERATOR_VERSION` |
| `pyproject.toml` `.python-version` | uv 管理、Python 3.12 固定 |

**テスト**：30 passed, 1 skipped（Python 3.12.13）。
skip は `test_every_op_has_an_interp_implementation` — `interp/ops.py` が未実装のため、理由付きで明示的にskip。#2 で解除する。

**検証**：レジストリが計画の数値を支えていることを独立に検算し、全件一致を確認した。

```
ops: 24 | uses_k: 10 | non-k: 14
space: [24, 552, 12144, 255024] | total: 267744 | d1-3: 12720
k-slot分布: {0: 26404, 1: 93110, 2: 102150, 3: 41040, 4: 5040}
共通部分の最小: 7 | 空になるAST: 0
```

**計画に書かれておらず、実装時に決めたこと**

- **`OP_NAMES = tuple(sorted(OP_REGISTRY))` を unrank の添字基準にした。**`unrank(r, i)` は固定並びが
  前提だが計画は並びを規定していなかった。辞書順にしたのは `OP_REGISTRY` の記述順（改訂版の表順）を
  後から編集しても添字が動かないようにするため。並びを変えても `semantic_hash` は不変で、
  影響を受けるのは `ast_id` の採番と seed 固定時の difficulty 4 抽出結果だけ
- **`uses_k` を `literal_domain` から導出せず手書きにした。**導出すると conformance テストの
  「`uses_k=True` のopだけが非空の値域を持つ」が常に真になり検査にならない
- **`ja_key` は全24opで `name` と同値。**フィールドは分けたまま
- **`shadows` は `ge` / `multiple_of` / `mul_k` の3つだけ。**改訂版 L275 の4件から導出。
  `desc`≡`[asc, reverse]` と `[square, abs]`≡`[square]` は単一opの話ではないので入れず、
  `behavior_hash` に委ねる（§2.6）
- **`CATEGORY_ORDER` を追加。**`canonical_order` 判定に後で必要
- **`BOKU_GENERATOR_VERSION` は `boku/__init__.py` に置いた。**置き場所が未規定だった

### #2 参照インタプリタ — 未着手

次のチャンク。`document_AST.md` §6 の注意点に従い、期待値は手書きで厚く書く。
このフェーズでは差分ランダムテストの相手（コード生成器）が存在せず、
`test_interp_ops.py` が実質唯一のガードになるため。

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

### #2 参照インタプリタ — 完了（2026-07-30）

24opの意味の手書き実装。**正解データの唯一の権威**（`document_AST.md` §2.7）。

**作ったもの**

| ファイル | 内容 |
| --- | --- |
| `boku/interp/ops.py` | 24opの意味。全opが `(xs, k) -> list[int]` の同一シグネチャ |
| `boku/interp/run.py` | `run(ast, xs, k)`。列の順に適用し、`xs` を複製して変更しない |
| `boku/limits.py` | 入力条件 L102-105（`xs`長さ0〜20、要素±100、`k` 1〜10） |
| `tests/test_interp_ops.py` | op別の手書き期待値。24op × 共通バテリー ＋ 境界ケース |
| `tests/test_interp_differential.py` | **別原理の実装との全数比較**（下記） |
| `tests/test_no_mutation.py` | `run()` と各opが入力を変更しない |
| `tests/test_golden_example.py` | 改訂版 L163-169 の問題例。ランダム1,000件で掲載コードと一致 |
| `tests/test_limits.py` | L102-105 の値、リテラル値域と `k` 値域の一致（L269） |

**テスト**：261 passed（0.32s、Python 3.12.13）。**skip はゼロ**になった。
`test_every_op_has_an_interp_implementation` の skip を解除し、
`OP_IMPLS` と `OP_REGISTRY` のキー集合一致が有効になっている。

**独立検証**：意味を**意図的に違う原理で**もう一度書き、全数比較した。1,779,600件が一致。

| 検証 | 件数 |
| --- | --- |
| 単一op 全数（要素−4〜4・長さ0〜4・`k` 1〜10） | 1,771,440 |
| L103 境界（±100 を含む15要素） | 240 |
| 3op操作列（12opから3個の全順列 × 6入力） | 7,920 |

原理の置き換えは、剰余→ビット検査、`sorted`→最小値の繰り返し取り出し、
スライス→添字ループ、乗算→加算の繰り返し。
`test_interp_ops.py` は期待値と実装を同じ人間が書くので思い違いが両方に同じ形で入り込むが、
原理を変えた実装ならそれを共有しにくい。

途中で1件の不一致が出たが、原因は**検証スクリプト側**の探索範囲不足だった
（`mul_k` 後の値1000を偶奇判定の探索範囲±400が覆えず偽陰性）。インタプリタ側の誤りではない。
探索を使わない定義に直して再実行し、全件一致した。

**計画に書かれておらず、実装時に決めたこと**

- **`test_interp_differential.py` を追加した（§7 に無いテスト）。**
  L281-286 の差分ランダムテストは相手のコード生成器がスコープ外のため成立せず、
  このフェーズでは手書き期待値が唯一のガードになる。その弱点を補うため常設化し、
  `document_AST.md` §7 にも追記した。コード生成器の実装後は補助に下がる
- **`boku/limits.py` を新設した。**L102-105 の入力条件の置き場所が未規定だった。
  `registry.py` は変更していない。代わりに `LITERAL_MIN/MAX == K_MIN/K_MAX`（L269）を
  `test_limits.py` で機械的に固定した
- **全opが `(xs, k)` の同一シグネチャを持つ。**`k` を参照しないopは `k` を無視する。
  `uses_k` で呼び分けるとディスパッチが分岐し、かつ参照インタプリタが `registry` の
  メタデータに実行時依存してしまう（L281-286 の独立性を損なう）
- **`run()` は構造検証をしない。**操作数や重複の検査は `validate.py`（#3）の担当（§2.7）。
  `run()` は `k` の範囲（L104）と未知op名だけを弾く。空ASTは恒等として複製を返す
- **`square` は `x * x`、`reverse` は `list(xs[::-1])`。**`op_` を全関数の接頭辞にして
  組み込み `abs` の遮蔽を避けた

### #3 SemanticAST と構造検証 — 未着手

次のチャンク。`semantic_ast.py` `validate.py` `schema.json` と、
`uniform_literal_domain`（§2.4 の一様具体化）の実装。

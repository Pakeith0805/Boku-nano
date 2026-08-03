# 実装計画：Boku-nano Phase 1 前半（意味AST層 ＋ 参照インタプリタ）

## Context

課題「日本語の指示から限定的なPython関数を生成するSLMのフルスクラッチ学習」の Phase 1 で、
自然言語より先に**問題の意味を表す中間表現（意味AST）**を作る。現在リポジトリには課題文2種のみでコードはゼロ。

意味ASTは下流3つの生成器すべての**唯一の起点**であり、後から作り直しが効かない層である。

| 消費側 | 意味ASTに要求すること |
| --- | --- |
| 参照インタプリタ | `(AST, xs, k) → list[int]` を素直に評価できる |
| コード生成器 | 同一ASTから複数スタイルの等価Pythonコードを吐ける |
| 日本語生成器 | op単位のスロットに承認済み表現辞書を差し込め、順序マーカーを連鎖できる |
| 検証・分割・選抜 | `semantic_hash` / `behavior_hash` / `difficulty` / op組合せ署名が取れる |

### 規範とする文書

**`芦原・倉林研究室_夏休み実習課題_Boku-nanoの開発_改訂版.md`（最終ver）のみを正とする。**
以下の行番号はすべてこの文書のもの。原版は参照履歴として扱う。

| 項目 | 値 | 出典 |
| --- | --- | --- |
| 操作 | 24種類。**1〜4個**を組合せ。同一opを2回以上使わない | L111 |
| op名 | 課題文の表が正式な識別子 | L113-157 |
| 適用順序 | **自由**。順序が違えば別の意味AST | L297 |
| 意味ASTの定義 | **操作列のみ。定数は含めない** | L256 |
| 意味AST空間 | 267,744種類。ここから **30,000〜100,000** を層化抽出 | L403-422, L397 |
| 展開例数 | 1意味ASTあたり最大20例 | L428 |
| リテラル値域 | `k` と同じ 1〜10 の整数。除外規定あり | L269-279 |
| `difficulty` | 操作の個数（1〜4） | L386 |
| 漏洩検査 | **5項目**。第5項が `behavior_hash` 重複なし | L516-536 |
| `xs` / `k` | 長さ0〜20、要素 −100〜100 / `k` は 1〜10 | L102-104 |
| 独立2実装 | 参照インタプリタとコード生成器をランダムテストで比較 | L281-286 |

### 前回計画からの変更点（大きい順）

1. **op数の上限が 1〜3 → 1〜4 で確定**（L111、2026-07-30確定）。目標件数に対して構造的に必要で、
   1〜3 では 12,720種類しかなく 30,000 に届かない。経緯は §8 の確認事項①（解決済み）に記録
2. **定数を意味ASTに含めない**（L256）。前回の「定数を含める」判断を撤回し、
   `ops` のインスタンスid 表記（`ge@k` / `ge@2`）を廃止して素のop名の列に戻す
3. **`behavior_hash` が課題文に明文化された**（L258, L388, L516-536）。
   前回は自前の設計だったが、いまは要件。ただし**用途は分割後の漏洩検査**であり、
   コーパス構築時の重複除去ではない。方針を「除去する」から「注記して報告する」に変える
4. **層化抽出が必須になった**（L413-422）。「難易度を均等にする」は明示的に否定された（L457）
5. **op名が確定**：`add_k` / `sub_k` / `mul_k`（`_k` 付き）、`double` / `triple`

---

## 1. 実装範囲

### 今回作るもの

意味ASTのデータ構造・検証 / op レジストリとリテラル値域 / 順位付け（unrank）による列挙と層化抽出 /
参照インタプリタ / 固定入力集合と `behavior_hash` / ASTコーパス構築スクリプト / テスト一式

### 今回作らないもの

以下は **Protocol の宣言と適合テストのフックのみ**とし、実装しない。

コード生成器（`codegen`） / 日本語生成器（`ja`） / コード→ASTパーサ /
バインディング生成器（展開層） / train/val/test 分割スクリプト / 漏洩検査スクリプト /
hidden test 生成器 / 解説文レコード（L338 が「残る課題」と明記）

意味AST層のロジック自体は **Python 標準ライブラリだけ**で書く。pydantic は入れない。
パッケージ管理・設定管理・実験管理には uv / Hydra / MLflow を使う（§11）。
意味の権威である参照インタプリタと列挙器に外部ライブラリを持ち込まないことが要点であり、
その周辺（実行の入口、設定、記録）は §11 のツールに任せる。

---

## 2. 確定した設計判断

### 2.1 AST は op名の順序付き列

```json
["ge", "double", "asc"]
```

L251 の例と完全に同形。定数も引数も持たない、**素のop名の平坦なリスト**。

- `difficulty` = `len(semantic_ast)`、1〜4
- **同一opを2回以上使わない**（L111）
- 適用順序が意味を持つ（`[asc, take_first]` ≠ `[take_first, asc]`、L297-302）

op名は L113-157 の表を正式な識別子として使う。`Counter(chain(*semantic_ast))` だけで
L458「各演算子の出現頻度を均す」の集計ができ、`grep` も効き、人間が一目で読める。

`MAX_OPS = 4` は L111 で確定しており（§8 確認事項①、2026-07-30に確定）、実装中に揺れない。
それでも `registry.py` の単一定数として置き、値をコードに散らさない。理由は不確定性への保険ではなく、
将来 Boku-1B で対象領域を広げる際の変更点を1箇所に閉じておくためである（§2.3 の `OP_REGISTRY` と同じ方針）。

### 2.2 列挙は unrank による層化抽出

#### 空間の大きさ（L403-411）

```
difficulty 1   24
difficulty 2   24 × 23              =     552
difficulty 3   24 × 23 × 22         =  12,144
difficulty 4   24 × 23 × 22 × 21    = 255,024
                                      ───────
合計                                   267,744
```

1〜3操作は合計 12,720 種類（全体の 4.8%）しかないため、**無作為抽出では4操作が95%を占める**。
L413 が要求するとおり `difficulty` ごとに件数を決めて層化抽出する。

#### 既定の配分（L416-421）

| difficulty | 件数 | 取り方 |
| ---: | ---: | --- |
| 1 | 24 | 全数 |
| 2 | 552 | 全数 |
| 3 | 12,144 | 全数 |
| 4 | `target − 12,720` | 255,024 から一様抽出 |
| | **target** | 既定 30,000（1〜3操作 42% / 4操作 58%） |

`target` は 30,000〜100,000 で指定する（Hydra 設定、§11）。**検証範囲は L397 の帯そのものとし、
`30,000 ≤ target ≤ 100,000` を外れたら拒否する。** 空間の上限（267,744）ではなく課題文の目安を
境界にするのは、帯の外の件数でコーパスを作れてしまうと、以降の検算（L424-437）とデータ規模表の
対応が黙って崩れるためである。
`alloc=[24,552,12144,17280]` の形で配分の明示指定もできるようにする
（合計が `target` と一致することを検証する）。この検証は Hydra の設定検証ではなく
`boku/semantics/enumeration.py` 側で行い、ライブラリに依存しない（§11 の依存の層）。

この帯は `MAX_OPS = 4`（§8 確認事項①で確定）を前提とする。仮に `MAX_OPS` を 3 に下げると
空間が 12,720 種類しかなく、帯を満たす `target` が存在せず必ずエラーになる。
これは意図した挙動であり、`MAX_OPS` を動かしたら L397 の目標件数の再検討が必要になることを
実行時に気づかせるための safety net として残す。

#### 255,024 を materialize しない

`unrank(difficulty, index) -> tuple[str, ...]` を実装する。
24個から r 個を順序付きで選ぶ組合せを下降階乗基数で番号付けし、番号から直接復元する。
抽出は `random.sample(range(N_r), n)` で行うので、空間全体を展開しない。

**副産物：op出現頻度が構成的に一様になる。** 24個のopは対称なので、全数を取る
difficulty 1〜3 では厳密に一様、difficulty 4 の一様抽出でも期待値が一様になる。
L458「各演算子の出現頻度を均す」が追加処理なしで満たされる。テストで検証する。

ただし**カテゴリ**の頻度は一様にならない（filter 10 : map 8 : order 3 : slice 3）。
L458 が求めているのは演算子単位なので問題ないが、`manifest.json` に両方を出す。

#### 順序について

`canonical_order`（カテゴリ順 抽出→変換→並べ替え→切り出し に従うか）はレコードに**記録するが、
列挙は制限しない**（L297 が順序自由と定めているため）。分析とアブレーションの材料としてのみ持つ。

### 2.3 op は 24 種類。レジストリのデータとして持つ

| カテゴリ | op名 | `k` 参照 |
| --- | --- | --- |
| filter | `even` `odd` `positive` `negative` `zero` | — |
| filter | `gt` `ge` `lt` `le` `multiple_of` | ✓ |
| map | `double` `triple` `negate` `abs` `square` | — |
| map | `add_k` `sub_k` `mul_k` | ✓ |
| order | `asc` `desc` `reverse` | — |
| slice | `every_other` | — |
| slice | `take_first` `take_last` | ✓ |

計 24（`k` を参照するもの 10、しないもの 14）。

**ハードコードせず `OP_REGISTRY` の中身として持つ。** 将来 Boku-1B で対象領域を広げる際に
この dict の差し替えだけで対応できる構造にする。`registry_version` を全レコードに記録。

### 2.4 定数は意味ASTに含めない（L256）

| 層 | 内容 | 用途 | 今回 |
| --- | --- | --- | --- |
| 意味AST | 操作列のみ | 分割の単位（L465） | **作る** |
| バインディング | 各`k`参照opを `k` のままか、リテラルに具体化するか | 展開層（最大20例／AST） | 値域定義のみ。生成器は作らない |

意味ASTには値ではなく**位置のメタ情報**だけを持たせる（`binding_slots`）。

#### リテラル値域（L269-279、展開層が使う）

リテラルは **`k` と同じ 1〜10 の整数**に限る。L269 の根拠が重要：
リテラル版のコードは必ず「参照インタプリタを `k` ＝そのリテラル値で評価した結果」と一致するので、
**パラメータ版とまったく同じ検証機構がそのまま使える**。0や負数を許すと対応する `k` が存在せず判定できない。

| op | 値域 | 除外の根拠（L273-277） |
| --- | --- | --- |
| `gt` `lt` `le` | 1〜10 | 除外なし。`lt`@1（`x < 1`）は `negative`（`x < 0`）とゼロの扱いが違うので保持 |
| `ge` | 2〜10 | `@1` は要素が整数なので `positive` と同一 |
| `multiple_of` | 3〜10 | `@1` 恒真、`@2` は `even` と同一 |
| `add_k` `sub_k` | 1〜10 | 除外なし（`@0` は値域外なので規定不要） |
| `mul_k` | 4〜10 | `@1` 恒等、`@2` は `double`、`@3` は `triple` と同一 |
| `take_first` `take_last` | 1〜10 | 除外なし |

リテラルに具体化したコードは `k` を参照しないが、**シグネチャは `solve(xs, k)` のまま保つ**（L279）。

#### 一様具体化の制約（L269 の帰結）

L269 の等価性が成立するのは、ASTが持つ `k` 参照スロットを**全て同一の値に具体化した場合**、
または**全て `k` のまま残した場合**に限る。スロットごとに別の値を入れると、
どの `k` での参照インタプリタ評価とも一致せず、検証機構が使えなくなる。

```
[ge@3, take_first@7]  run(ast, xs, 3) でも run(ast, xs, 7) でもない
[ge@3, take_first@k]  k を動かしても ge 側が追従しないので同様に不可
```

したがってバインディングは次の2形態だけを許す。

1. 全スロットを `k` のまま（パラメータ版）。検証は任意の `k` で行える
2. 全スロットを同一のリテラル `v` に具体化（リテラル版）。検証は `k = v` で行う

**帰結：複数スロットASTで使えるリテラルは、各スロットの値域の共通部分になる。**
`[ge, multiple_of, mul_k]` なら `{2..10} ∩ {3..10} ∩ {4..10} = {4..10}` の7値。
これをレコードの `uniform_literal_domain` に持たせ、展開層が値域を再計算しなくてよいようにする。

この制約は例外的な事情ではない。`k` 参照スロットを2個以上持つASTが空間の過半を占める。

```
k参照スロット 0個    26,404 ( 9.9%)
k参照スロット 1個    93,110 (34.8%)
k参照スロット 2個   102,150 (38.2%)   ← ここから共通部分が効く
k参照スロット 3個    41,040 (15.3%)
k参照スロット 4個     5,040 ( 1.9%)
  2個以上           148,230 (55.4%)
```

共通部分が空になるASTは存在せず、最小でも7値が残る（値域の下限除外が最大3個までのため）。
制約を課しても展開の余地は失われない。テストで両方を検証する。

#### 展開層への申し送り

`k` 参照opを1つも持たないASTは **26,404件**（14, 14·13, 14·13·12, 14·13·12·11 の和 = 全体の 9.9%）。
既定配分 30,000 では約 4,000件（13%）が残る。これらはバインディングによる多様性がゼロなので、
L428 の「最大20例」を**日本語表現 × コード形式だけで**満たす必要がある。
L292 の「操作あたり10〜30種類の日本語表現」× コード形式7種があれば足りるが、展開層の設計時に確認すること。

この申し送りは「最大20例」を**展開時の上限**と読んだ場合にのみ必要になる。
選抜時の上限と読むなら不要である。課題文はどちらとも確定できない（§8 確認事項⑪）。

`k` 参照opを持つASTでは、リテラルのバリエーションは `uniform_literal_domain` の要素数に等しい
（1スロットなら7〜10、複数スロットなら共通部分の 7〜10）。パラメータ版1通りを加えても
最大11通りにとどまるため、20例を埋めるには日本語表現とコード形式との積が前提になる。

### 2.5 `behavior_hash`：除去ではなく注記する

L258 と L516-536 が要求する検査である。**順序を自由にしたことの直接の帰結**として、
可換な操作対では異なる意味ASTが同一の関数を表す。

```
[even, positive] と [positive, even]     フィルタ同士は可換
[even, desc]     と [desc, even]         フィルタと整列も可換
[double, triple] と [triple, double]     どちらも ×6
[square, abs]    と [square]             二乗は常に非負なので abs が恒等
```

これらは `semantic_hash` が異なるため第1項を通過し、生成コードも文字列としては異なるため
第4項も通過してしまう。しかしモデルにとっては同一の課題である。

```python
semantic_hash = sha256(canonical_json(semantic_ast))
behavior_hash = sha256(json([run(ast, xs, k) for (xs, k) in BEHAVIOR_PROBE_SET]))
```

#### 方針：コーパス構築時に除去しない

L536 は「重複が見つかった場合は、**テスト側のレコードを除外する**」と定めている。つまり
処理する場所は**分割後の漏洩検査**であって、コーパス構築時ではない。除去を構築時に前倒しすると

- L416-421 の層化配分の「全数」（difficulty 2 の 552 など）が崩れる
- 30,000〜100,000 という目標件数が意図せず減る

したがって**構築時は算出して記録し、衝突を報告するだけ**にする。除去は分割スクリプト（スコープ外）の仕事。
`--drop-behavior-duplicates` フラグは用意するが**既定は off**
（L816「意味重複を残す場合と除去する場合の比較」の実験条件として残す）。

同様に、常に空になるAST（`[even, odd]` など）や恒等になるASTも**除去せず**、
`always_empty` / `is_identity` として記録し件数を報告する。選抜（L455-461）の判断材料にする。

#### 固定入力集合

L536 は「境界値と乱数を混ぜた固定の入力集合（例: 境界値20件＋ランダム50件）」「全レコードで共通」と定める。
入力は `(xs, k)` の対にする（opが `k` を参照するため）。

**`k` が 1〜10 を網羅していれば、リテラル具体化版の振る舞いもすべてカバーされる**
（L269 の「リテラル版 ＝ `k`＝そのリテラル値での評価」という性質の帰結）。これは設計上の重要な含意。
ただし成立条件は §2.4 の**一様具体化**である。スロットごとに別の値を入れた版は
どの `k` での評価とも一致しないため、この固定入力集合ではカバーされない。

識別力の要件：

- `k` は 1〜10 を網羅
- `gt` と `ge`、`lt` と `le` を分けるため、`xs` に `k` と等しい値を含むケース
- `mul_k` と `double` / `triple` を分けるため、`k ∉ {2, 3}` のケース
- `multiple_of` と `even` を分けるため、`k ≠ 2` のケース
- `ge` と `positive` を分けるため、`k ≠ 1` のケース
- `lt` と `negative` を分けるため、`k = 1` かつ `xs` に `0` を含むケース
- `take_first` と `take_last` を分けるため、`len(xs) > k` と `len(xs) < k` の両方
- 長さ 0（空リスト）、1、2、3、5、20
- 全負・全正・全ゼロ・重複値・正負混在
- 要素は L103 に従い −100 以上 100 以下

境界値20件＋ランダム50件を出発点とし、**単一opのAST 24 個の `behavior_hash` が全て相異なる**まで増やす
（上限256）。`probes/behavior_probe_set_v1.jsonl` として凍結し、`probe_set_version` を全レコードに記録する。

### 2.6 shadow 関係と正準形の宣言

L273-277 のリテラル除外で `mul_k`@2/@3、`multiple_of`@2、`ge`@1 の衝突は消えるが、
**将来コード→ASTパーサを書くときの正準形**を今のうちに宣言しておく。

- `docs/canonical_forms.md` に衝突ペアと正準形の対応表を書く
- `OpSpec` に `shadows: tuple[str, ...]` を持たせる
- パーサ本体は実装しない。宣言のみ

**`docs/canonical_forms.md` の冒頭に明記すること**：往復はASTの同一性としては閉じない。
`x * 2` をパースすると `double` になり、`mul_k` をリテラル2に具体化したものだったとしても戻らない。
したがって将来パーサを実装する際の受け入れ条件は、**ASTの同一性ではなく意味的等価性**とする。

```python
# 将来の受け入れテスト（今回は書かない。docs に記載だけしておく）
assert run(parse(emit(ast)), xs, k) == run(ast, xs, k)
```

`desc` と `[asc, reverse]` は生成コードが異なるためパース衝突ではないが振る舞いは同一で、
これは §2.5 の `behavior_hash` が拾う。

### 2.7 正規化は代数的書き換えをしない

`validate.py` が行うのは**構造検証のみ**とする。

- `difficulty` が 1〜`MAX_OPS`
- 同一opの重複がない
- 未知のop名がない

`[even, odd] → 空`、`[negate, abs] → [abs]`、`[square, abs] → [square]`、`[asc, desc] → [desc]`
のような等価則は**手書きしない**。手書きの代数則は間違えると正解データそのものを汚染する。
縮退の検出は §2.5 の `behavior_hash` に任せる。
**参照インタプリタが意味の唯一の権威であり続ける。**

順序自由なので、例えば「並べ替えは最後のものだけが効く」は**偽**である
（`[asc, take_first, desc]` の `asc` は `take_first` が何を取るかを決めているので効いている）。
構造的な枝刈りは安全に書けない。filter のソートも行わない（順序が意味を持つ表現でソートは情報を壊す）。

### 2.8 レジストリに意味を持たせない

```python
@dataclass(frozen=True, slots=True)
class OpSpec:
    name: str                              # "ge"（L113-157 の正式名）
    category: Literal["filter", "map", "order", "slice"]
    uses_k: bool
    literal_domain: tuple[int, ...]        # §2.4 の値域。uses_k=False なら ()
    ja_key: str                            # 日本語表現辞書の引き当てキー
    shadows: tuple[str, ...] = ()
    notes: str = ""
```

**lambda、コード文字列、`eval`、`apply` メソッドを一切置かない。** 意味は `interp/ops.py` に手書きする。

これは L281-286 が要求する「各意味ASTから、独立した二つのプログラムを作る」を成立させるためである。
共有ソースがあると、そこにバグがあった場合に両実装が同じように間違え、
「両者の出力をランダムテストで比較してコード生成器自身のバグを検出する」仕掛けが素通りする。

両者は `test_registry_conformance.py` のキー集合一致テストだけで同期する。このテストが検査するのは
「存在と形式」だけで、「意味が合っているか」は検査しない。意味の検査は差分ランダムテストの担当であり、
役割を混ぜないこと。

---

## 3. 固定入力集合と hidden test の分離

`behavior_hash` 用の固定入力集合（§2.5）と、評価用の hidden test は**目的が違うので混ぜない**。

| | 固定入力集合（今回作る） | hidden test（作らない） |
| --- | --- | --- |
| 目的 | 意味の同定 | 評価 |
| 設計方針 | 識別力を最優先。現実的な分布は考えない | 現実的な入力分布 |
| 出典 | L536 | L707「コード作成時に使用したテストとは異なる hidden test」 |

将来の分離を担保するため以下を用意する。

- 別モジュールに分ける（`boku/probes/` と、将来の `boku/evalgen/`）
- 乱数の名前空間を分ける（固定入力集合は専用の固定シードを使い `manifest.json` に記録）
- `boku/probes/behavior_probes.py` に `load_probe_inputs() -> set[tuple[tuple[int, ...], int]]` を公開する。
  将来の hidden test 生成器がこれを読み、**衝突する `(xs, k)` を除外できる**ようにしておく

---

## 4. レコード形式

`data/ast/asts.jsonl`（フィールド名は L358-381 のデータレコードに合わせる）：

```json
{
  "ast_id": "ast-000001",
  "semantic_ast": ["ge", "double", "asc"],
  "difficulty": 3,
  "categories": ["filter", "map", "order"],
  "op_set": ["asc", "double", "ge"],
  "canonical_order": true,
  "binding_slots": [{"index": 0, "op": "ge", "literal_domain": [2,3,4,5,6,7,8,9,10]}],
  "uniform_literal_domain": [2,3,4,5,6,7,8,9,10],
  "uses_k": true,
  "semantic_hash": "...",
  "behavior_hash": "...",
  "always_empty": false,
  "is_identity": false,
  "source": "rule",
  "created_at": "2026-07-30T12:00:00Z",
  "generator_version": "v0.1",
  "schema_version": 1,
  "registry_version": "ops24-v1",
  "probe_set_version": "v1"
}
```

| フィールド | 用途 |
| --- | --- |
| `semantic_ast` | AST本体（L362 と同形）。演算子頻度の集計キー（L458） |
| `difficulty` | 操作の個数 1〜4（L386）。層化抽出の層、選抜の配分保持（L457） |
| `op_set` | 順序を落としてソートしたop集合。**予約ペアの引き当てキー**。L472 の予約は順序非依存でなければ L485「個々の操作は学習したが組合せは見ていない」状況が作れない |
| `binding_slots` | `k` 参照opの位置と、展開層が使えるリテラル値域（§2.4）。**具体値は持たない** |
| `uniform_literal_domain` | 全スロットに同一値を入れる場合に使えるリテラルの集合＝各スロット値域の共通部分（§2.4）。`k` 参照opがなければ `[]`。**リテラル版はこの集合からのみ選ぶ**。L269 の検証等価性の成立条件 |
| `semantic_hash` | 分割の単位（L465）。漏洩検査第1項（L520） |
| `behavior_hash` | 漏洩検査第5項（L524）。可換対と意味的縮退の検出 |
| `always_empty` / `is_identity` | 選抜（L455-461）の判断材料。**除去はしない**（§2.5） |
| `canonical_order` | 分析とアブレーション用 |

`manifest.json`：seed、`target`、difficulty別の配分と実件数、`MAX_OPS`、各 version、
op出現頻度、カテゴリ出現頻度、`canonical_order` 比率、
`k` 参照スロット数の分布と `uniform_literal_domain` の最小サイズ（§2.4）、
**`behavior_hash` の異なり数・最大衝突グループ長・衝突に関与するAST件数**、
`always_empty` / `is_identity` の件数、出力値の絶対値の最大桁数（§6）。

### provenance 3項目

`source` / `created_at` / `generator_version` は L795-808 の由来管理要件に対応して残す。

- **`source`** — AST層では**常に `"rule"`**。L57「正解の意味構造、コード、テストはルールベースで作成し、
  教師モデルは自然言語表現を増やす役割に限定する」および L53「開発支援AIに個々の学習サンプルを
  直接書かせる」の禁止により、教師由来・開発支援AI由来の意味ASTは存在してはいけない。
  `assert source == "rule"` をテストにして**常時ガード**にする
- **`created_at`** — 各ハッシュと `ast_id` の入力に含めない（同一seedでの再実行が別物になるため）
- **`generator_version`** — 単一定数 `BOKU_GENERATOR_VERSION` を手で上げる

---

## 5. ファイル構成

```
boku/
  semantics/
    semantic_ast.py   # SemanticAST（frozen dataclass, slots=True）
                      #   to_dict / from_dict / canonical_json / difficulty / op_set
                      #   categories / canonical_order / binding_slots
    registry.py       # OP_REGISTRY（24 op、意味なし）, OpSpec, MAX_OPS, リテラル値域
    validate.py       # §2.7 の構造検証
    schema.json       # JSON Schema
    unrank.py         # 下降階乗基数での順位付け。unrank(r, i) / rank(ops) / count(r)
    enumeration.py    # 層化抽出（全数 ＋ random.sample による一様抽出）
    fingerprint.py    # semantic_hash / behavior_hash / always_empty / is_identity
    corpus.py         # asts.jsonl と manifest.json の読み書き
  interp/
    ops.py            # 手書きの意味（唯一の権威）
    run.py            # run(ast, xs, k)
  probes/
    behavior_probes.py  # 固定入力集合の生成 ＋ load_probe_inputs()
  codegen/__init__.py   # Protocol: emit(ast, binding, style) -> str   ← 今回は宣言のみ
  ja/__init__.py        # Protocol: render(ast, binding, rng) -> str    ← 今回は宣言のみ
probes/behavior_probe_set_v1.jsonl
conf/                   # Hydra の設定（§11）。boku/ 側はこれを知らない
  config.yaml           #   target / seed / alloc / out / drop_behavior_duplicates
  probe_set.yaml        #   probe_set.version / 境界値・ランダムの件数 / 上限256
docs/
  canonical_forms.md
  open_questions.md
  dev_ai_usage.md
scripts/
  build_probe_set.py    # Hydra と MLflow を触るのはこの層だけ（§11）
  build_ast_corpus.py
tests/
pyproject.toml          # 依存を [project] と [dependency-groups] dev に分ける（§11）
uv.lock                 # コミットする。来歴管理（L795-808）に効く
.python-version         # 3.12
```

`run(ast, xs, k)` は入力 `xs` を複製し破壊的変更をしない。
`k` 参照opは `k` を直接受け取る（AST側に引数がないので `resolve` は不要）。
`*args` の可変長ディスパッチは使わない（監査しやすさ優先）。

#### モジュール名で標準ライブラリを隠さない

`semantic_ast.py` は `ast.py` にしない。パッケージ経由の絶対importなら標準ライブラリの `ast` が
優先されるため通常は問題ないが、`python boku/semantics/validate.py` のようにファイルを直接実行すると
そのディレクトリが `sys.path` の先頭に入り、`import ast` がローカルの `ast.py` に解決されて
**`ast.parse` が消える**。本課題は検証条件（L445）と Syntax-valid率（L685）で標準の `ast.parse` に
依存するため、実行方法によって壊れる名前は最初から避ける。

`enumeration.py` も同じ理由で `enumerate.py` にしない（`from boku.semantics import enumerate` が
組み込み関数 `enumerate` を隠す）。

### `docs/dev_ai_usage.md`

L808「開発支援AIを使用した場合は、どの範囲の実装に使用したかを併せて記録する」への対応。
L42-47 の許可範囲（参照インタプリタ、コード生成器・日本語文生成器、検証・重複除去・分割スクリプト）と
L51-55 の禁止事項に照らし、どのモジュールに Claude Code / Codex を使ったかを記録する。
**その出力は生成器のソースコードであって合成データそのものではない**ことを明記する。
将来 `THIRD_PARTY.md`（L805）に統合する。

### `ja` 生成器への申し送り

L297-314 の要求。**操作が2個以上のASTでは、日本語指示に適用順序を明示する接続表現を必ず含める。**
`difficulty` 3以上では順序マーカーを**連鎖**させ、どの操作が何番目かが一意に読み取れるようにする。

```
[even, add_k, desc, take_first]
  まず偶数だけを残し、次にそれぞれにkを加え、降順に並べてから先頭k個を取る
```

承認済み表現辞書は次の3カテゴリを別に持つ必要がある。

1. op 別の表現（L316-321 の例：「偶数の要素だけを抽出する」「2で割り切れる値のみを残す」…）
2. **順序マーカー**（「〜してから〜」「〜した後で〜」「まず〜、次に〜」）と、その連鎖規則
3. リテラルのスロット表現（`ge` を `k` のまま →「k以上」、リテラル5 →「5以上」、L267）

L314「difficultyが3以上の指示文は特に注意して承認すること」を承認フローに反映する。
既定配分では **difficulty 4 が全体の58%** を占めるため、順序マーカー連鎖の品質がデータ全体の品質を決める。

---

## 6. 参照インタプリタ実装時の注意

手書き・退屈・監査可能な実装にする。正解データの権威なので凝らない。

| 箇所 | 注意 |
| --- | --- |
| `odd` | `x % 2 != 0` を正規形とする。Pythonの`%`は正の除数に対して非負を返すため（`-3 % 2 == 1`）、`== 1` でもL103の−100〜100の全整数で同じ結果になるが、意図が明確な `!= 0` に統一する。`== 1` が負数で崩れるのはC/Javaの挙動であり、Pythonには当てはまらない |
| `multiple_of` | `x % k == 0`。`k >= 1`（L104）なのでゼロ除算は起きないが assert する |
| `take_last` | `xs[-k:]`。**`k == 0` だと全リストが返る**。`k >= 1` を assert する |
| `take_first` / `take_last` | `k > len(xs)` は全リスト（Pythonスライス準拠）。境界値テストの必須項目 |
| `every_other` | 「1個おき」の曖昧性を `xs[::2]`（先頭から）に確定し、docstring に明記 |
| `reverse` vs `desc` | `xs[::-1]` と `sorted(xs, reverse=True)` は別op。潰さない |
| `square` → `abs` | 二乗は常に非負なので `abs` が恒等になる（L534）。**インタプリタ側で特別扱いしない。** `behavior_hash` が縮退として検出する |
| 出力の桁数 | `[mul_k, square]` 等で大きな値になり得る。L105 は出力が範囲を超えることを許している。Phase 2 のトークナイザ設計（語彙4,096）に影響するので**出力値の絶対値の最大桁数を `manifest.json` に記録** |

---

## 7. テスト

| テスト | 内容 |
| --- | --- |
| `test_unrank.py` | `rank(unrank(r, i)) == i` が r=1..4 の全範囲で成立（255,024 まで全数検査）。`unrank` の像が重複なし・同一op重複なし。`count(r)` が 24 / 552 / 12,144 / 255,024 |
| `test_ast_roundtrip.py` | `from_dict(to_dict(ast)) == ast`、`canonical_json` の安定性 |
| `test_validate.py` | `difficulty` 0 / 5、同一opの重複、未知op名を弾く |
| `test_registry_conformance.py` | レジストリがちょうど 24 op。名前が L113-157 の表と一致。全opに `interp` 実装が存在し逆も真。`uses_k=True` のopだけが非空の `literal_domain` を持つ |
| `test_literal_domains.py` | §2.4 の表どおり。`ge` に 1 が無い、`multiple_of` に 1,2 が無い、`mul_k` に 1,2,3 が無い、`lt` に 1 が**ある**、全値域が 1〜10 に収まる |
| `test_uniform_literal_domain.py` | 全267,744ASTで `uniform_literal_domain` が各スロット値域の共通部分と一致。**空になるASTが1件も無く、最小サイズが7**。`[ge, multiple_of, mul_k]` が `{4..10}`。`k` 参照opを持たないASTは `[]`。`k`参照スロット数の分布が 26,404 / 93,110 / 102,150 / 41,040 / 5,040 |
| `test_literal_binding_equivalence.py` | 一様具体化の等価性（§2.4）。`uniform_literal_domain` の各 `v` について、全スロットを `v` に固定した評価が `run(ast, xs, v)` と一致する。**混在バインディングが一致しない**ことも反例で示し、制約が本物であることを固定する |
| `test_interp_ops.py` | op別の単体テスト。負数・0・空リスト・`k > len(xs)`・重複値を必ず含む |
| `test_interp_differential.py` | **意味を意図的に違う原理でもう一度書き、全数比較する。**（剰余の代わりにビット検査、`sorted` の代わりに最小値の繰り返し取り出し、スライスの代わりに添字ループ、乗算の代わりに加算の繰り返し）。L281-286 の差分ランダムテストは相手のコード生成器がスコープ外のため成立せず、`test_interp_ops.py` は期待値と実装を同じ人間が書くので思い違いが両方に同じ形で入り込む。原理を変えた実装ならその思い違いを共有しにくい。**コード生成器の実装後は、そちらが本来の差分テストを担うのでこのファイルの役割は補助に下がる** |
| `test_probe_discriminates.py` | 単一opのAST 24 個の `behavior_hash` が全て相異なる |
| `test_known_collisions.py` | 既知の可換対と縮退が同一 `behavior_hash` になる：`[even, positive]`/`[positive, even]`、`[even, desc]`/`[desc, even]`、`[double, triple]`/`[triple, double]`、`[square, abs]`/`[square]`（L529-534 の全例） |
| `test_no_mutation.py` | `run()` が入力 `xs` を変更しない |
| `test_stratified_alloc.py` | 既定 target 30,000 で配分が 24 / 552 / 12,144 / 17,280。difficulty 1〜3 が全数。同一seedで再現。target が範囲外なら拒否 |
| `test_op_frequency.py` | 既定配分でのop出現頻度が一様から一定範囲内（§2.2 の構成的一様性の確認） |
| `test_no_teacher_in_semantics.py` | 全レコードが `source == "rule"` |
| `test_core_has_no_external_deps.py` | §11 の依存の層を固定する。`boku/semantics/` `boku/interp/` `boku/probes/` の全モジュールの import 文を走査し、標準ライブラリと `boku.*` 以外を import していないこと（`hydra`・`mlflow` が意味の権威側に染み出さないための歯止め）。走査には標準の `ast` を使う——この検査自体が §5 の「モジュール名で標準ライブラリを隠さない」判断の受益者である |
| `test_hash_excludes_timestamp.py` | `created_at` を差し替えても各ハッシュと `ast_id` が不変 |
| `test_golden_example.py` | L163-169 の問題例。`["ge", "double", "asc"]` の参照インタプリタ出力が掲載コード `sorted([x * 2 for x in xs if x >= k])` とランダム入力1,000件で完全一致 |

`test_known_collisions.py` が §2.5 の要点を守る。**課題文が挙げている縮退例を検出できないなら
漏洩検査第5項が機能しない**ので、固定入力集合の受け入れ条件として扱う。

---

## 8. `docs/open_questions.md` に記録する事項

課題文の解釈をどう決めたかは報告書の材料になるので、解決済みも根拠付きで残す。

未解決の要確認事項はない。実装に入れる状態である。

### 解決済み

1. **op数の上限は 1〜4 で確定（2026-07-30）。** 最終ver L111 の「1〜4個」に従う。
   `MAX_OPS = 4`。以前受けていた「1〜3で固定していい（倉林先生本人に確認）」との指示は、
   **学生本人の確認により 2026-07-30 に破棄され、1〜4 で確定した。**
   以後この判断を再検討しない。
   根拠は二つある。第一に、最終verが唯一の正であり L111 が「1〜4個」と定めている。
   第二に、1〜4 は目標件数に対して構造的に必要である（1〜3では空間が 12,720種類しかなく、
   定数をASTに含めない方針のまま L397 の 30,000〜100,000 に届かない）。
   この確定により、`MAX_OPS` は将来の対象領域拡張（Boku-1B）以外で動かす定数ではなくなった

2. **原版の問題例が4opだった矛盾** — 最終ver L163-169 で3op（`["ge","double","asc"]`）に修正され、
   op数上限も 1〜4 になったため解消
3. **`mul_k`@2 / `mul_k`@3 の除外** — 最終ver L275 に明記され、課題文の要件になった。
   あわせて `ge`@1 = `positive`（要素が整数のため）も課題文側で追加されている
4. **リテラル値域** — 最終ver L269 で 1〜10 に確定。根拠（リテラル版＝`k`＝リテラル値での評価なので
   同じ検証機構が使える）も明記された
5. **`behavior_hash` による可換対の検出** — 最終ver L258 / L516-536 で漏洩検査第5項として要件化された

### 実装上の解釈（課題文に明記がないもの）

6. **`behavior_hash` の衝突をコーパス構築時に除去しない**（§2.5）。L536 が「テスト側のレコードを
   除外する」と定めており処理場所は分割後なので、構築時は記録と報告に留める。
   前倒しすると L416-421 の「全数」配分と L397 の目標件数が崩れる
7. **`always_empty` / `is_identity` のASTも除去しない**。L455-461 の選抜規則に除去の指示がないため、
   注記して件数を報告し判断を選抜段に委ねる
8. **予約ペアは順序非依存と解釈した**（`op_set`）。L472 の予約で L485 の状況を作るには
   `[even, desc]` と `[desc, even]` の両方を除外する必要がある
9. **カテゴリ出現頻度は一様にしない**。L458 が求めているのは演算子単位の頻度であり、
   カテゴリのop数（10 : 8 : 3 : 3）から一様にはならない。両方を `manifest.json` に出す
10. **リテラル具体化は全スロット一様と解釈した**（§2.4）。L269 の検証等価性が成立する条件であり、
    L267 の日本語側の言い換え（「k以上」→「5以上」）も単一の値を前提に書かれている。
    ただし複数の `k` 参照opを持つASTで、スロットごとに別の値を許すかは課題文に明記がない。
    一様と解釈した結果、使えるリテラルは各スロット値域の共通部分になる（該当は空間の 55.4%）。
    混在を許す場合は参照インタプリタ側にスロット別の引数を導入する必要があり、
    L269 の「パラメータ版とまったく同じ検証機構をそのまま適用できる」という利点を失う
11. **「最大20例」は展開時の上限と読んだ**。L428（`### 意味表現の生成`）の「1意味ASTあたり最大20例」と
    L461（`## データの検証と選抜`）の「一つの意味ASTにつき最大20例などの上限を設ける」は、
    展開時の上限とも選抜時の上限とも読め、どちらの意味かは課題文から確定できない
    （`CHANGES.md` の「残る課題」2 が同じ点を未解決として挙げている）。
    本計画は展開時の上限として扱っており、§2.4 の申し送り（`k` 参照opを持たないASTは
    日本語表現 × コード形式だけで20例を満たす必要がある）はこの読みに依存している。
    選抜時のみの上限と読むなら、あの申し送りは不要になる。
    どちらの読みでもデータ規模表には到達するため、数値上の不整合は生じない

---

## 9. 検証手順

実行はすべて `uv run` を通す。設定の上書きは Hydra 記法（`key=value`）である（§11）。

```powershell
# 1. 全テスト
uv run pytest -q

# 2. 固定入力集合を生成して凍結
uv run python -m scripts.build_probe_set probe_set.version=v1
#    → 単一op 24個の behavior_hash が全て相異なるまで自動で増やし、件数を報告

# 3. AST コーパスを構築（既定）
uv run python -m scripts.build_ast_corpus target=30000 seed=0
#    → MLflow に1 runとして記録される（params / metrics / manifest.json は §11）
```

期待される出力：

- difficulty別の配分が **24 / 552 / 12,144 / 17,280**、合計 30,000（L416-421 と一致）
- difficulty 1〜3 が全数であること
- 構造検証通過 ＝ 全件（列挙器が無効ASTを作らないことの確認）
- op出現頻度が一様から一定範囲内。カテゴリ頻度は 10:8:3:3 に近い比率
- `behavior_hash` の異なり数と最大衝突グループ長を報告。
  `[even, positive]`/`[positive, even]` のような既知の可換対が同一グループに入っていること
- `always_empty` / `is_identity` の件数を報告
- `canonical_order` 比率を報告
- `k` 参照スロット数の分布を報告。`uniform_literal_domain` が**全件で非空・最小7**であること（§2.4）
- 出力値の絶対値の最大桁数を報告（Phase 2 への申し送り）

```powershell
# 4. 目標件数の上限側
uv run python -m scripts.build_ast_corpus target=100000 seed=0
#    → difficulty 4 の抽出が 87,280 件になること

# 5. 意味重複を除去した場合との比較（L816 の研究課題の条件）
uv run python -m scripts.build_ast_corpus target=30000 drop_behavior_duplicates=true seed=0
#    → 除去件数を報告。既定 off との差分が可換対と縮退の総量になる
#    → MLflow 上で 手順3 の run と並べて差分を読む（§11）

# 6. 再現性
uv run python -m scripts.build_ast_corpus target=30000 seed=0 out=data/ast/asts_rerun.jsonl
#    → created_at 以外が完全一致すること
#    → 相対パスが Hydra の作業ディレクトリに逃げないこと（§11 の注意2）

# 7. 目標件数の帯の外は拒否されること（§2.2）
uv run python -m scripts.build_ast_corpus target=20000 seed=0
uv run python -m scripts.build_ast_corpus target=150000 seed=0
#    → いずれも L397 の 30,000〜100,000 を外れるためエラーで停止すること
```

**人手による受け入れ確認**：`asts.jsonl` を数十件、特に difficulty 4 を重点的に目視し、
操作列を読んで「どんな問題か」が一目で分かること。
difficulty 4 が全体の58%を占め、そこが日本語生成の難所（順序マーカーの連鎖）になるため、
可読性を受け入れ基準に含める。

---

## 10. 今回スコープ外だが、余地を残しておくもの

| 項目 | 残しておくフック |
| --- | --- |
| バインディング生成器（展開層） | `binding_slots`（値域込み）、`uniform_literal_domain`（一様具体化で使える値の共通部分）、L269 の「リテラル版＝`k`＝リテラル値での評価」という検証の等価性 |
| コード→ASTパーサ | `OpSpec.shadows`、`docs/canonical_forms.md` |
| コード生成器・日本語生成器 | `codegen` / `ja` の Protocol、`ja_key`（op表現・順序マーカー連鎖・リテラルスロットの3カテゴリ） |
| train/val/test 分割（L469-483） | `semantic_hash`（分割単位）、`op_set`（順序非依存のペア予約）、`difficulty`（層の保持） |
| 漏洩検査5項目（L516-536） | `semantic_hash`（第1項）、`behavior_hash`（第5項）、`load_probe_inputs()` |
| hidden test 生成器（L707） | `load_probe_inputs()` による `(xs, k)` の衝突回避 |
| 解説文レコード（L338 が残る課題と明記） | スキーマに `record_type` を追加できる構造 |
| トークナイザ（Phase 2） | 出力値の最大桁数を `manifest.json` に記録。リテラルは 1〜10 の10種に限定されている |
| 比較実験（L709-723） | `MAX_OPS` / `target` / `drop_behavior_duplicates` / `registry_version` をレコードとマニフェストに記録 |
| 順序多様性のアブレーション | `canonical_order` フィールド |

---

## 11. ツールと実験管理（uv / Hydra / MLflow）

2026-07-30 に決定。三つの役割を分けて使う。

| ツール | 役割 | 導入時期 |
| --- | --- | --- |
| **uv** | Python本体とパッケージの管理、実行の入口 | いま |
| **Hydra** | スクリプトの設定管理（`target` / `seed` / `alloc` など） | ASTコーパス構築スクリプトから |
| **MLflow** | 実行の記録と比較実験 | ASTコーパス構築から（学習指標は Phase 4） |

課題文はこれらを禁じていない。L181 の「NumPy、Pandasなどの外部ライブラリ」は`## 対象外の要素`
にある記述で、**生成する `solve` 関数が使ってはいけないもの**を指す。パイプラインの実装については
L71 が既存部品の利用を許しており、L233（推論ライブラリのバージョン）・L236（seed）・
L762（再現可能な機械学習実験）・L795-808（来歴管理）はむしろ実験管理の導入を後押しする。

### 依存の層を分ける

**意味の権威に外部ライブラリを持ち込まない。**これが唯一の制約である。

| 層 | 許す依存 |
| --- | --- |
| `boku/semantics/` `boku/interp/` `boku/probes/` | **標準ライブラリのみ** |
| `scripts/` | ＋ `hydra-core`（`omegaconf`）、`mlflow` |
| `tests/` | ＋ `pytest` |

参照インタプリタは意味の唯一の権威（§2.7）であり、`OP_REGISTRY` は意味を持たないデータ（§2.8）
である。ここに設定ライブラリや実験管理の都合が混ざると、監査の対象が「手書きの退屈なコード」
から「ライブラリの挙動込み」に広がる。Hydra と MLflow を触るのは `scripts/` の入口だけとし、
`boku/` 側は素の引数を受け取る関数のままにする。この境界はテストで固定する（§7）。

### uv

- **Python を 3.12 に固定する。**`.python-version` に `3.12` を書き、`uv python install 3.12` で用意する。
  現状この機械には 3.13 と 3.14 しかなく計画（3.12）とずれているが、uv 導入でこのずれが消える
- 実行は `uv run` を通す（`uv run pytest -q`）。§9 のコマンドもこの形にした
- **`uv.lock` をコミットする。**L795-808 の来歴管理と L233 のバージョン記録に直接効く
- 依存は `pyproject.toml` の `[project] dependencies`（実行時）と
  `[dependency-groups] dev`（pytest など）に分ける

### Hydra

設定を `conf/` の YAML に出し、スクリプトの入口を Hydra 経由にする。実装時に踏む注意が2点ある。

1. **CLI記法が変わる。**`--target 30000 --seed 0` は Hydra では `target=30000 seed=0` になる。
   §9 の検証手順はこの記法に書き換えてある
2. **Hydra は既定で作業ディレクトリを変える**（`outputs/YYYY-MM-DD/HH-MM-SS/`）。
   `data/ast/asts.jsonl` のような相対パスが意図しない場所に出る。`hydra.job.chdir=False` を
   明示するか、パスを `hydra.utils.get_original_cwd()` 起点で解決すること

`--alloc 24,552,12144,17280`（§2.2）のようなリスト引数は、YAML 側では素のリストで持ち、
CLI からの上書きは `alloc=[24,552,12144,17280]` の形になる。

### MLflow

ASTコーパス構築を1 run として記録する。`manifest.json` に出す項目（§4）がそのまま params と
metrics になる。

- **params**：`target` / `seed` / `MAX_OPS` / `registry_version` / `probe_set_version` /
  `generator_version` / `drop_behavior_duplicates`
- **metrics**：difficulty別の実件数 / op出現頻度の偏り / `behavior_hash` の異なり数と
  最大衝突グループ長 / `always_empty`・`is_identity` の件数 / `k`参照スロット数の分布 /
  出力値の絶対値の最大桁数
- **artifacts**：`manifest.json`、`probes/behavior_probe_set_v1.jsonl`

これは L709-723 の比較実験と L816「意味重複を残す場合と除去する場合の比較」にそのまま使える。
§9 手順5（`drop_behavior_duplicates=true`）は既定 off の run との差分として読める。
Phase 4 では L682-692 の評価指標を同じ tracking に載せる。

**`manifest.json` は MLflow に載せても残す。** MLflow のストアはツールの都合で移動・消去され得るが、
`manifest.json` はコーパスと同じ場所に置かれた由来の記録であり、L795-808 が求めているのはそちら。
**MLflow は閲覧と比較のための索引であって、由来の正本ではない。**

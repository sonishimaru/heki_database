# 性癖データベース

キャラクターを構成要素に分解し、そこから生まれる「性癖」を辞典として引けるようにするデータベース。
VTuberデザイン辞典のような **ファセット絞り込み型のカタログ** として作っている。

- データは `data/` 以下の YAML（人間が書く／レビューする）
- `tools/build.py` が検証して `docs/data/db.json` を生成
- `docs/` が依存ゼロの静的サイト（GitHub Pages でそのまま公開できる）

現在の収録数: **127 名 / 228 要素 / 23 性癖 / 25 軸**

## 考え方

「性癖」は要素そのものではなく、要素の **配置** から生まれる。
「無表情」も「余裕」も、それ単体では性癖ではない。落差・限定・秘匿といった構造と組み合わさって初めて効く。
そこでこのデータベースは 4 層に分けている。

| 層 | 中身 | 例 |
| --- | --- | --- |
| **axis（軸）** | 分類の座標系。4 分類 × 25 軸 | 外見 / 髪色、関係性 / 関係の状態 |
| **element（構成要素）** | 辞典の見出し語。定義・効き方・相性・対比を持つ | メガネ、糸目、長髪、手、両片思い |
| **pattern（性癖）** | 要素の配置を文法で記述したもの | 余裕の崩壊、限界まで隠す |
| **character** | 実在キャラを要素へ分解した実例 | シャーロック・ホームズ |

### 見出し語の粒度

**「メガネ」「糸目」「長髪」「手」「両片思い」くらいの解像度**で立てる。ここを外すと辞典として使えなくなる。

- 通りのいい言葉ひとつに寄せる。「ロングストレート」ではなく「長髪」、「取り繕いの下の本音」ではなく「建前と本音」。
- 細かく割らない。「たれ目」「つり目」「糸目」は分けるが、「うなじの見える短髪」は「短髪」と「うなじ」に解いて既存語へ寄せる。
- 迷ったら新語を立てず、既存の見出し語の `aliases` に足す。
- ニュアンスの違いは `summary` / `description` / `effect` で書き分ける。見出し語を増やして解決しない。

### 分類の軸

トップレベルは **外見・性格・関係性・物語役割** の 4 分類。

| 分類 | 軸 |
| --- | --- |
| 外見 | 髪型 / 髪色 / 目の形 / 目の色 / 顔 / 体格 / 部位 / 痕 / 服装 / 記号職 / 小物 / 種族 |
| 性格 | 気質 / 信条 / 傷 / 話し方 / 癖・仕草 |
| 関係性 | 立場 / 関係の型 / 関係の状態 |
| 物語役割 | 役割 / 結末 / ギャップ / 秘密 / 限定・反復 |

- 髪色と髪型、目の色と目の形は**別の軸**。独立に選べるものは混ぜない（ピンク髪×ツインテールで掛け合わせ検索できる）。
- **記号職**（メイド・巫女・シスター・ナース・魔女・騎士・執事・アイドル）は衣装と役割が一体化した記号として外見に置く。
- **種族**は吸血鬼・天使・悪魔・エルフ・竜・鬼・幽霊の解像度で立て、「人外」はその他の受け皿。
- 立場（令嬢・従者・上に立つ人）や年齢差（年上・年下）は関係の初期値を決めるので**関係性**に置く。
- ギャップ・秘密・限定・反復は物語の演出装置なので**物語役割**に置く。

### 粒度の憲法

1. **見出し語は pixiv百科事典 / Danbooru にタグ・記事として実在する通り語を優先する。**
   検索して確かめられる粒度アンカー。物語役割の軸のみ概念語を許す。
2. **1 軸 1 ファセット。** 色と形のように独立に選べるものは軸を分ける。
3. **1 軸の語数に上限は置かない。** 引ける語は足していく。ただし引きにくくなったら
   軸の分割を検討し、実例が長期間 0 の語は降格を疑う。
4. **名前は 7 文字以内を目安にする。** 見出し語も性癖名も。長い言い回しは名前ではなく
   `aliases` と `summary` に置く。

### 性癖の文法

パターンは必ず次の 5 項目で記述する。ここを埋められないものは、まだ性癖として言語化できていない。

| 項目 | 内容 |
| --- | --- |
| `subject` | 主体の初期条件（誰が） |
| `delta` | 何が変化するか（落差の中身） |
| `trigger` | 何によって発火するか |
| `condition` | どの範囲でのみ成立するか（限定性） |
| `observer` | 誰の視点から観測されると効くか |

加えて `requires`（これが無いと成立しない要素）、`intensifiers`（強化する要素）、
`breaks_when`（壊れる条件）を持たせている。`breaks_when` は「なぜ滑るのか」を記録するための欄で、
実作にあたって最も参照される項目になる。

## 使い方

```bash
python3 tools/build.py           # 検証 + docs/data/db.json を生成
python3 tools/build.py --check   # 検証のみ（CI と同じ）

cd docs && python3 -m http.server 8000   # http://localhost:8000 で閲覧
```

サイトでできること:

- **キャラ名鑑** — 全文検索 ＋ 構成要素（大分類 / 軸 / 要素 / 比重）／性癖（パターン / タグ）で絞り込み
- **性癖パターン** — 成立の文法、必要要素、壊れる条件、実例、*要素上は成立しうる人物*（自動推論）
- **要素辞典** — 見出し語ごとの定義・効き方・相性・対比、逆引き（この要素を持つ人物 / 使う性癖）
- キャラ詳細では、軸ごとの内訳と **構成比バー**、要素が重なる他の人物を表示
- **分析** — 収集パイプラインのダッシュボード。キャラ別の状態（レビュー済み / 自動下書き / キュー待機）、
  構成レーン、最終分析日、欠けている軸、要素辞典のカバレッジを一覧する

## データ収集元

データベースに入る情報は、軸ごとに「どこから採るのが確実か」が違う。
収集元を混ぜると精度が落ちる——映像から年齢を推定する、静止画から性格を判定する、といった取り違えが起きる。
そこで収集を**レーン**に分け、各レーンは担当する軸の証拠ファイルだけを作る。判定はレーンの後段で一括して行う。

### 入口: 公開の検索可能なリソース

素材は原則、公開の検索可能なリソースから `fetch.py` で取得して `work/sources/` に置く。
信頼度の層で使い分ける。

| 層 | リソース | 取れるもの | 取得方法 |
| --- | --- | --- | --- |
| 一次（公式） | アニメ・ゲーム公式サイトのキャラページ | 確定プロフィール、公式立ち絵、キービジュアル | `fetch.py page <URL>` |
| 二次（構造化） | AniList（GraphQL・認証不要） | プロフィール文・公式画像・出演作品 | `fetch.py anilist <名前>` |
| 二次（構造化） | **Danbooru 関連タグ集計** | **外見の群衆合意**（そのキャラの投稿にどのタグが何%付くか） | `fetch.py danbooru <タグ>` |
| 二次（百科） | pixiv百科事典・Wikipedia・Fandom | 容姿・性格・人間関係・作中の出来事の記述 | `fetch.py page <URL>` |

Danbooru は `wd_map.yaml` と同じ語彙なので、関連タグの頻度がそのまま外見の出現率として
`merge.py --danbooru` に入る。数千枚の人力タグの合意であり、少数フレームの機械タグ付けより強い。
百科系のテキストは `facts.py` が「資料に書かれている事実」だけを出典つきで facts.yaml に下書きし、
人が確認してから分類に渡す。

取得のマナー: 1 ページ・1 クエリ単位で取得し、巡回はしない。取得物は `work/`（gitignore 済み）に
留めて再配布せず、リポジトリに入るのは抽出した事実と出典 URL だけ。

### 標準ルート（最短）

ほとんどのキャラはローカル素材なしで、公開リソースだけで下書きまで行ける。

```bash
# 1. 取得（公式キャラページ、pixiv百科事典、AniList、Danbooru）
python3 tools/ingest/fetch.py page "https://<公式サイト>/character/xxx"
python3 tools/ingest/fetch.py page "https://dic.pixiv.net/a/<記事名>"
python3 tools/ingest/fetch.py anilist "Character Name" --download-image
python3 tools/ingest/fetch.py danbooru "character_(work)"

# 2. 資料 → 事実の下書き（出典つき。人が確認する）
python3 tools/ingest/facts.py --character 名前 --pages work/sources/page_*.txt work/sources/anilist_*.json

# 3. 分類（非外見）と統合（外見は Danbooru 合意から）
python3 tools/ingest/classify.py --character 名前 --facts work/facts.yaml --out work/classify.json
python3 tools/ingest/merge.py --danbooru work/sources/danbooru_*.json --vision work/classify.json \
    --name 名前 --kana かな --work 作品名
```

映像・台詞のレーンは、このルートで埋まらない軸（癖・仕草・話し方の実測）を上げたいときに足す。

### 自動更新（GitHub Actions）

取得〜分析〜統合は GitHub Actions が毎日無人で実行する（`.github/workflows/ingest.yml`）。
Actions のランナーには通常のネットワークがあるので、開発環境の制限に関係なく動く。

1. **`data/queue.yaml` にキャラクターを足す**（これが人のやる唯一の操作）。
   Danbooru タグ・AniList 名・資料 URL のうち書いたレーンだけが動く。
2. push するか毎日 05:00 JST に、`tools/ingest/auto.py` が新規と期限切れ（30 日超）を
   最大 12 件処理し、`data/characters_auto.yaml` へ書き込んでコミットする。
   見出し語を足した後は `refresh_all` を on にして手動実行すると、全件へ新しい語彙を当て直す。
3. 再取得ではレーン単位で置き換える。外見だけ更新しても、前回の分類結果や summary は消えない。
4. Gemini を使う工程（facts / classify）はリポジトリの Secrets に `GEMINI_API_KEY` を
   登録すると有効になる（Settings → Secrets and variables → Actions）。無ければ
   Danbooru 合意による外見だけが更新される。

`characters_auto.yaml` は機械専用の下書き置き場で、`analysis.method` に `auto` が付く。
レビューして採用するときはエントリを `characters.yaml` へ移して磨く。同じ id が両方にあれば
手書き側が優先されるので、移した後の自動更新に上書きされる心配はない。

### レーン一覧

| レーン | 収集元 | 確実に採れる軸 | 技術 | 出力 |
| --- | --- | --- | --- | --- |
| ① 静止画 | **Danbooru 関連タグ集計**、公式立ち絵・設定画（なければ映像フレーム） | 外見（髪・目・顔・体・服装・小物） | `fetch.py danbooru` / WD-Tagger + `wd_map.yaml` | `danbooru_*.json` / `tags.json` |
| ② 映像 | 本編アニメ・MV・カットシーン | 癖・仕草、演技の差分、関係の距離感 | PySceneDetect → Gemini Vision 観察（flash） | `observations.json` |
| ③ 台詞 | 字幕・スクリプト・書き起こし | 話し方（一人称・語尾・敬語率） | `speech.py`（決定的な集計、モデル不使用） | `speech.json` |
| ④ 資料 | 公式サイト・pixiv百科事典・AniList・Wikipedia | 属性（年齢・種族・立場）、関係の型、展開 | `fetch.py page/anilist` → `facts.py` 下書き → 人が確認 | `facts.yaml` |

レーンの後段に判定と統合が続く。

| 工程 | 入力 | 技術 |
| --- | --- | --- |
| 分類（非外見） | ②③④の証拠ファイル | Gemini pro（テキストのみ）: `classify.py` |
| 統合 | ①の `tags.json` / `danbooru_*.json` ＋ 分類の `classify.json` | 決定的なルール: `merge.py` |
| 検証 | YAML | `build.py` ＋ 人。**性癖の成立判定は人だけ** |

### 使い分けの原則

- **カット割り（AdaptiveDetector）は②レーン内の前処理**であって、収集の本体ではない。
  映像を使うのは「動きでしか分からないもの」（仕草、演技の差分、距離の詰め方）のためだけ。
- **年齢・種族・立場のような明記された事実は④から採る。** 映像や静止画から推定させない。
- **外見は Danbooru 合意 → 公式立ち絵 → 映像フレームの順で強い。** 群衆の人力タグ、次に設定画、
  映像フレームは衣装差分の補完という序列。
- **話し方は③が最も確実。** 映像を眺めて口調を判定させるより、台詞を数十行集計するほうが強い。
- **有名キャラは④＋分類だけで下書きができる。** ②は仕草の精度を上げたいときに足す。
  全レーンを毎回回す必要はなく、埋めたい軸に対応するレーンだけ動かせばよい。

### 実行例

```bash
pip install 'scenedetect[opencv]' onnxruntime huggingface_hub pillow numpy pandas
export GEMINI_API_KEY=...

# ① 静止画: Danbooru 合意を取るか、手持ちの設定画・立ち絵にタグを付ける
python3 tools/ingest/fetch.py danbooru "character_(work)"
python3 tools/ingest/tagger.py work/art/*.png --out work/tags.json

# ② 映像: カット割り → シーン観察（--resume で中断から再開）
python3 tools/ingest/scenes.py video.mp4 --out work/frames --per-cut 3
python3 tools/ingest/observe.py --cuts work/frames/cuts.json \
    --cast "少女=アーニャ, 父=ロイド" --out work/observations.json

# ③ 台詞: その人物の行を 1 行 1 台詞で抜き出して集計
python3 tools/ingest/speech.py lines.txt --out work/speech.json

# ④ 資料: 公開資料から下書きして人が確認する（手書きなら facts_template.yaml）
python3 tools/ingest/fetch.py page "https://dic.pixiv.net/a/<記事名>"
python3 tools/ingest/facts.py --character 名前 --pages work/sources/page_*.txt
$EDITOR work/facts.yaml

# 分類: 揃っている証拠だけ渡す（どれも任意、最低一つ）
python3 tools/ingest/classify.py --character アーニャ \
    --facts work/facts.yaml --observations work/observations.json --speech work/speech.json \
    --out work/classify.json

# 統合: characters.yaml の断片を得る
python3 tools/ingest/merge.py --tags work/tags.json --vision work/classify.json \
    --name アーニャ --kana あーにゃ --work 作品名
```

API キーがない環境では `--prompt-only` でプロンプトを出して AI Studio に貼り、応答を `--from-json` で読み込める。

### 各工程が「してはいけないこと」

- **observe.py は分類しない。** 語彙を渡さず、人格の判定を禁止し、行動と表情の記述だけをさせる。
- **classify.py は画像を見ない。外見を判定しない。** 判定には根拠（どのレーンのどこ）の列挙を必須にしてあり、
  根拠のない判定・語彙にない id・外見軸への越境は検証で自動的に落ちる。
- **tagger.py は外見しか対応表にない。** 静止画から読めない概念（身長・姿勢・うなじ・形見）は
  `wd_map.yaml` の末尾に理由付きで除外してある。
- **speech.py はモデルを使わない。** 数えられるものは数える。解釈はしない。
- **fetch.py は取得しかしない。** 判定・要約はせず、原文を work/sources/ に保存するだけ。
- **facts.py は資料にない情報を書かない。** 解釈・印象は禁止し、各事実に出典を付けさせる。
  矛盾する記述は採らずに notes へ回す。出力は下書きで、人の確認を経てから classify に渡す。
- **merge.py は性癖を決めない。** `patterns` は人が `breaks_when` と照らして書く。

### 比重の決め方

「**繰り返し現れる特徴ほどその人物の骨格に近い**」を全レーンに同じ原理で適用する。

- 外見（WD-Tagger）: フレーム出現率 60% 以上かつスコア 0.6 以上で `core`、
  25% 以上またはスコア 0.85 以上で `sub`、それ未満は `spice`。
- 非外見（classify）: 複数の場面・複数のレーンにまたがれば `core`、限られれば `sub`、一度きりなら `spice`。

`note` にはタグ名・スコア・出現枚数、または根拠レーンとシーン番号がそのまま残るので、後から検証できる。

作業用の中間ファイル（動画・フレーム・観察記録・タグ・facts）は `work/` に置き、コミットしない。

## データの足し方

### 要素を足す

`data/elements/*.yaml` に追記する。

```yaml
- id: megane              # 小文字ケバブケース、全体で一意
  name: メガネ
  kana: めがね
  aliases: [眼鏡]         # 表記ゆれ・近い言い方はここへ寄せる
  axis: appearance.item   # data/axes.yaml にある <group>.<axis>
  summary: 顔の中央に置かれる境界物。外すと表情が解禁される。
  description: >-
    知性の記号としてより、着脱できる仕切りとして強い。
    反射で目を隠す、ずり上げる、拭くなど、感情処理の時間稼ぎに使える動作が多い。
  effect: 表情の前に一枚の層を置き、外す瞬間を切替点にする。
  pairs_with: [shokunin, jitome, keigo]
  contrasts_with: []
  tags: [定番, 切替]
```

`summary` は一行の定義、`effect` は「受け手にどう効くか」。この二つを分けているのが要点で、
`effect` を書けない要素は、まだ要素として切り出せていない可能性が高い。
また、既存の見出し語で言い換えられるものは新しく立てない（上の「見出し語の粒度」を参照）。

### 性癖を足す

`data/patterns.yaml` に、上の 5 項目を埋めて追記する。`requires` / `intensifiers` は既存の要素 id を指す。

### キャラクターを足す

`data/characters.yaml` に追記する。`weight` は `core`（骨格）/ `sub`（補強）/ `spice`（一点差し）。

`analysis` に分析方法を残せる（`method` / `model` / `frames` / `cuts` / `date`）。
パイプラインから入れた場合は `merge.py` が自動で埋める。

```yaml
- id: sherlock-holmes
  name: シャーロック・ホームズ
  kana: しゃーろっくほーむず
  work: シャーロック・ホームズ シリーズ
  year: 1887
  author: アーサー・コナン・ドイル
  summary: 観察の精度で世界を読み切る一方、生活能力と情緒だけが欠落している探偵。
  elements:
    - {id: kansatsu, weight: core, note: 靴の泥と袖の擦れから経歴を再構成する}
    - {id: zubora, weight: sub}
  patterns: [kanzen-no-hokorobi]
```

追記したら `python3 tools/build.py` を実行する。id の重複、未知の参照、必須項目の欠落、
`weight` の誤りはすべてビルド時に落ちる。

## 収録方針

現代作品のキャラクターも収録する。ただし記述は「どの要素で構成されているか」という**分析**に限り、
本文・画像・設定資料は転載しない。分析に使った動画やフレームもリポジトリには入れない（`work/` は gitignore）。
実在の人物は対象にしない。

### キャラクター画像の扱い

サイトには参考画像を出すが、**画像ファイルはリポジトリに持たない**。保持するのは出典の URL だけで、
表示にはクレジットと出典ページへのリンクを必ず添える。

```yaml
  image:
    url: https://s4.anilist.co/file/anilistcdn/character/large/...   # 参照先
    page: https://anilist.co/character/00000                         # 出典ページ
    credit: AniList
```

自動取り込みでは AniList から取得した分が入る（`merge.py --anilist`）。手書きの `characters.yaml` にも
同じ形で書ける。出典が明示できない画像は載せない。

画像が無いキャラクター、および読み込みに失敗した場合は、**分析済みの髪色・目の色から組み立てた色見本**を
代わりに出す。借り物ではなく自前のデータが見た目になるので、画像が一枚も無くても一覧は成立する。

## 公開

`docs/` を GitHub Pages のソースに設定すればそのまま公開できる
（Settings → Pages → Source: `Deploy from a branch`、Branch: 対象ブランチ / `/docs`）。
ビルド成果物 `docs/data/db.json` はコミットに含めている。

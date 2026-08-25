# 性癖データベース

キャラクターを構成要素に分解し、そこから生まれる「性癖」を辞典として引けるようにするデータベース。
VTuberデザイン辞典のような **ファセット絞り込み型のカタログ** として作っている。

- データは `data/` 以下の YAML（人間が書く／レビューする）
- `tools/build.py` が検証して `docs/data/db.json` を生成
- `docs/` が依存ゼロの静的サイト（GitHub Pages でそのまま公開できる）

現在の収録数: **20 名 / 144 要素 / 23 性癖 / 21 軸**

## 考え方

「性癖」は要素そのものではなく、要素の **配置** から生まれる。
「無表情」も「余裕」も、それ単体では性癖ではない。落差・限定・秘匿といった構造と組み合わさって初めて効く。
そこでこのデータベースは 4 層に分けている。

| 層 | 中身 | 例 |
| --- | --- | --- |
| **axis（軸）** | 分類の座標系。7 分類 × 21 軸 | 外見 / 体・部位、関係 / 関係の状態 |
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

| 分類 | 軸 |
| --- | --- |
| 外見 | 髪 / 目 / 顔 / 体・部位 / 服装 / 小物 |
| 属性 | 年齢 / 種族 / 立場 |
| 性格 | 気質 / 信条 / 傷 |
| 振る舞い | 話し方 / 癖・仕草 |
| 関係 | 関係の型 / 関係の状態 |
| 展開 | 役割 / 結末 |
| 構造 | ギャップ / 秘密 / 限定・反復 |

「体・部位」（手、うなじ、鎖骨、背中、喉仏）と「関係の状態」（両片思い、片思い、共依存、すれ違い）は、
性癖としては最も大きい枠なので独立させている。

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

## 取り込みパイプライン（動画からの分析）

現代作品のキャラクターは、映像から機械的に分解してから人が確認する。
精度の要は二つ。**工程ごとに担当する軸を分けること**と、**観察と分類を分けること**。
数カットの静止画から性格や関係を直接判定させると、モデルが作品知識で補完した
「それらしい嘘」が混ざる。そこで「見たままを記録する工程」と「記録を横断して判定する工程」を
別のコールに割り、判定には必ず根拠シーンの番号を要求する。

| # | 工程 | 道具 | 担当 |
| --- | --- | --- | --- |
| 1 | カット割り | PySceneDetect `AdaptiveDetector` | 代表フレームの抽出 |
| 2 | シーン観察 | Gemini Vision（既定 `gemini-2.5-flash`） | 空間・時間・演技・人物の行動を**見たまま記録**。分類はしない |
| 3 | 静止画タグ付け | WD-Tagger（`wd-swinv2-tagger-v3`） | 外見（髪・目・顔・体・服装・小物） |
| 4 | 横断分類 | Gemini（既定 `gemini-2.5-pro`、テキストのみ） | 全シーンの観察記録から外見以外の軸を判定 |
| 5 | 統合 | `merge.py`（決定的なルール） | 比重と確度の決定、YAML 断片の出力 |
| 6 | 検証 | `build.py` ＋ 人 | 参照整合性。**性癖の成立判定は人だけ** |

観察（2）はシーン数ぶん呼ぶので安い flash、分類（4）は一人につき一回で判断力が要るので pro、と
モデルを分けている。`GEMINI_OBSERVE_MODEL` / `GEMINI_CLASSIFY_MODEL` で差し替え可能。

```bash
pip install 'scenedetect[opencv]' onnxruntime huggingface_hub pillow numpy pandas
export GEMINI_API_KEY=...

# 1. カット割りして代表フレームを抜く
python3 tools/ingest/scenes.py video.mp4 --out work/frames --per-cut 3

# 2. シーンごとに観察（--resume で中断から再開できる）
python3 tools/ingest/observe.py --cuts work/frames/cuts.json \
    --cast "少女=アーニャ, 父=ロイド" --out work/observations.json

# 3. 観察が選んだフレーム（observations.json 内 tagger_frames）を WD-Tagger にかける
python3 tools/ingest/tagger.py work/frames/cut-0012-02.jpg ... --out work/tags.json

# 4. 一人ぶんの観察を横断して分類
python3 tools/ingest/classify.py --observations work/observations.json \
    --character アーニャ --tags work/tags.json --out work/classify.json

# 5. 統合して characters.yaml の断片を得る
python3 tools/ingest/merge.py --tags work/tags.json --vision work/classify.json \
    --name アーニャ --kana あーにゃ --work 作品名 --cuts 42
```

API キーがない環境では、`--prompt-only` でプロンプトを出して AI Studio に貼り、
応答を保存して `classify.py --from-json` で読み込める。

### 各工程が「してはいけないこと」

- **observe.py は分類しない。** 語彙を渡さず、性格の判定を禁止し、行動と表情の記述だけをさせる。
- **classify.py は画像を見ない。外見を判定しない。** 判定には根拠シーンの列挙を必須にしてあり、
  根拠シーンのない判定・語彙にない id・外見軸への越境は検証で自動的に落ちる。
- **tagger.py は外見しか対応表にない。** 静止画から読めない概念（身長・姿勢・うなじ・形見）は
  `wd_map.yaml` の末尾に理由付きで除外してある。
- **merge.py は性癖を決めない。** 要素が揃っていることと性癖が成立していることは別の判断で、
  `patterns` は人が `breaks_when` と照らして書く。

### 比重の決め方

「**繰り返し観察される特徴ほどその人物の骨格に近い**」を両系統に同じ原理で適用する。

- 外見（WD-Tagger）: フレーム出現率 60% 以上かつスコア 0.6 以上で `core`、
  25% 以上またはスコア 0.85 以上で `sub`、それ未満は `spice`。
- 非外見（classify）: 複数シーンにまたがれば `core`、場面が限られれば `sub`、一度きりなら `spice`。

`note` にはタグ名・スコア・出現枚数、または根拠シーン番号がそのまま残るので、後から検証できる。

### タグの対応表

`tools/ingest/wd_map.yaml` が Danbooru 語彙と見出し語を繋いでいる。
新しい見出し語を足したら、対応する Danbooru タグもここに書く。

作業用の中間ファイル（動画・フレーム・観察記録・タグ）は `work/` に置き、コミットしない。

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

## 公開

`docs/` を GitHub Pages のソースに設定すればそのまま公開できる
（Settings → Pages → Source: `Deploy from a branch`、Branch: 対象ブランチ / `/docs`）。
ビルド成果物 `docs/data/db.json` はコミットに含めている。

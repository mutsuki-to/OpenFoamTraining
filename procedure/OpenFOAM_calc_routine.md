PyRth採用にあたっての# OpenFOAM 数値計算ルーティン (CHT / Zth抽出ワークフロー)

## 0. このドキュメントの位置づけ

何を計算するにも共通する**作業の流れ・分岐・検査点（ゲート）**を固定し、毎回の手戻りを減らすための上位文書。

- **このドキュメントが扱うもの**: ステップの並び、依存関係、フィードバックループ、各ステップの「次へ進んでよい条件（ゲート）」
- **このドキュメントが扱わないもの**: 各ステップの具体的なコマンド・ファイル内容 → ステップ別の詳細手順書に分離（一覧は §1.1 索引 / §9）
- **題材**: パワーデバイス模擬（chip / DBC / baseplate / TIM の固体多領域CHT、Zth抽出）。ただし流れ自体は他プロジェクト（例: 室内エアコン気流CFD）にも転用可能。**問題定義（ステップ1）が変われば下流の中身は変わる**が、骨格は変わらない。

---

## 1. 全体像（依存グラフ）

線形の9段ではなく、**設定の2波・検証の3点・出力のA/B分岐・5→4bのフィードバック**を持つ。

```
[1] 問題定義
      │
[2] アウトプット定義 ──► 予測値の手計算(1D抵抗 + 拡がり抵抗 → 予測定常Zth)
      │                         └─ step6a / step7 の「物差し」として保持
      ▼
[3] 形状モデル(STL) + surfaceCheck
      │
[0'] 初期化：前フェーズをコピー
      │  （クリーンは foamCleanTutorials。rm -rf 0 [0-9]* は 0.orig 事故）
      ▼
[4a] メッシュ生成系の設定 ◄──────────────┐
   blockMesh / snappy / topoSet(cellZone) │
      ▼                                   │ 実スナップZ座標・実パッチ名を
[5] メッシュ生成 + checkMesh ─────────────┤ 4bへフィードバック（必須）
   cellZone数 / bounding box / skewness   │  cat .../boundary, checkMesh で確認
      ▼                                   │
[4b] メッシュ依存の設定 ──────────────────┘
   changeDict(実パッチ名) / 底面boxToFace(実Z) / createPatch / decomposePar
      ▼
[6] ソルバ実行
   ├─[6a] 起動時sanity  ◄ ここで早期に弾く（発熱cell数 / fvOptions / 全領域 / 収支）
   └─[6b] 計算中monitoring（Min/max T / ΔT非崩壊 / h残差）
      ▼
   log + 時刻フィールド
      ├───────────────────────────┬───────────────────────────┐
      ▼ (ブランチA：ログ駆動)      ▼ (ブランチB：フィールド駆動)
[9a] log → Zth(t) 抽出           [8] foamToVTK / paraFoam -builtin
      ▼ (zth_calc, name-anchored)  温度分布 / 放熱経路 / メッシュ確認
[9b] 構造関数(PyRth, lanczos)
      ▼
[7] 最終妥当性検証 ◄── 予測値 / T3Ster実測 と照合
   エネルギー収支 / 定常Zth / 拡がり抵抗 / 構造関数の層対応
   （随時：Δt(Di数)感度・メッシュ感度・材料感度）
```

**読み方の要点（線形手順書では落ちる3点）**

1. **設定ファイルは2波に割れる**（後述 §3）。`4a → 5 → 4b` の順で、5→4b にフィードバックが必ず入る。
2. **検証は3点に分散する**（後述 §4）。完走後にまとめて検証すると、設定ミスで長時間を捨てる。
3. **出力はA/Bに分岐する**（後述 §6）。Zth(t)は **ParaViewではなくソルバログ**から出る。ParaViewを一度も開かずにZthは取れる。

### 1.1 手順書インデックス（各ステップ → 詳細手順書）

| Step | 内容 | 手順書ファイル |
|---|---|---|
| 1〜3 | 問題定義 / 出力定義 / STL作成 | 本書 §2（+ `OpenFOAM_solid_CHT_procedure.md`） |
| **4a** | メッシュ生成系の設定（pre-mesh） | `OpenFOAM_procedure_4a_mesh_config.md` |
| **5** | メッシュ生成 + checkMesh採取 | `OpenFOAM_procedure_5_mesh_gen.md` |
| **4b** | メッシュ依存の設定（post-mesh） | `OpenFOAM_procedure_4b_meshdep_config.md` |
| **6** | ソルバ実行（6a起動時/6b実行中） | `OpenFOAM_procedure_6_solver_run.md` |
| **7** | 妥当性検証 | `OpenFOAM_procedure_7_validation.md` |
| **8** | ParaView（ブランチB） | `OpenFOAM_procedure_8_paraview.md` |
| **9a** | Zth(t)抽出（ブランチA前段） | `OpenFOAM_procedure_9a_zth_calc.md`（+ `zth_calc.py`） |
| **9b** | 構造関数（PyRth, ブランチA後段） | `OpenFOAM_procedure_9b_pyrth_structure.md` |
| 9a/9b | 入出力契約 | `OpenFOAM_branchA_io_contract.md` |

> 4a〜9 は実機検証済みの専用手順書あり。1〜3 は本書§2 と既存の一般手順書でカバー。詳細・参考資料は §9。

---

## 2. 各ステップの目的・成果物・ゲート

「ゲート」＝これが満たされない限り次へ進まない条件。これがルーティンの本体。

### [1] 問題定義
- **目的**: 物理問題を計算可能な仕様に落とす
- **成果物**: 積層構造（材料・寸法・Z座標範囲）／物性（k, ρ, Cp）／発熱条件（層・総W）／冷却条件（境界温度・接触面位置）／界面熱抵抗 Rth[cm²K/W]／目標 endTime
- **ゲート**:
  - [ ] 各層の熱時定数 τ ≈ L²/α を見積もり、**最大τ を持つ層**から endTime（τの3〜5倍）を決めた
  - [ ] エネルギーが閉じる境界条件になっている（発熱の出口が一意：側面zeroGradient＋底面fixedValue 等）

### [2] アウトプット定義
- **目的**: 何を出すかを先に決め、それが強制する設定を確定する
- **成果物**: 欲しい量のリスト（Zth(t) / 定常Zth / 構造関数 / 温度分布 …）＋ **予測値の手計算**
- **ゲート**:
  - [ ] 1D熱抵抗＋拡がり抵抗で **予測定常Zth を1つ計算**した（例: 0.323 + 1.2(はんだ,小面積で支配的) + 0.063(TIM) ≈ 1.586 K/W。界面は面積換算 Rth[K/W]=Rth[m²K/W]/A）
  - [ ] §5の「出力→強制設定」表で、必要な設定が洗い出されている
  - 注: この予測値は step6a で桁を即判定する物差し、step7 で誤差%を出す基準になる

### [3] 形状モデル（STL）
- **目的**: 各層を個別STLとして出力
- **成果物**: 層ごとの `.stl`（FreeCAD、Z軸上向き、冷却面が下）
- **ゲート**:
  - [ ] 全STLが `Surface is closed`（`surfaceCheck`）
  - [ ] 隣接層の境界Z座標が一致（0.01mm精度）
  - [ ] 薄すぎる層（≲セルサイズ）は隣接層へ統合 or refinement見直し済み

### [0'] 初期化（コピー）
- **目的**: 前フェーズから派生し、計算結果だけ除く
- **ゲート**:
  - [ ] クリーンは `foamCleanTutorials`（`rm -rf 0 [0-9]*` は **0.orig も消す事故**）
  - [ ] `processor*/` `log.*` 旧時刻ディレクトリを持ち込んでいない

### [4a] メッシュ生成系の設定
- **目的**: メッシュ出力に依存しない設定を全部書く
- **成果物**: blockMeshDict / snappyHexMeshDict / (surfaceFeatureExtractDict) / topoSetDict(cellZone) / meshQualityDict
- **ゲート**:
  - [ ] `scale` はスカラー記法（`scale 0.001`、ベクトルは不可）
  - [ ] `locationsInMesh` は **SI単位(m)**（STLのscaleは読み込み時のみ適用、ここには効かない）
  - [ ] 直方体積層なら稜線抽出（features）は省略可と判断済み
  - [ ] cellZoneは contiguous な直方体なら `topoSet`(boxToCell) が `locationsInMesh` より確実

### [5] メッシュ生成 + checkMesh
- **目的**: メッシュを作り、**4bが必要とする実測値を採取する**
- **成果物**: `constant/polyMesh` → 分割後 `constant/<region>/polyMesh`
- **ゲート（＝4bへ渡す採取項目）**:
  - [ ] cellZone数 = 領域数（`checkMesh | grep cellZone`）
  - [ ] bounding box が全層を内包
  - [ ] skewness を確認（4超でも固体伝導は実用上可、ただし記録）
  - [ ] **実スナップ底面Z座標**を控えた（設計-3.94mm に対し実-3.948mm 等のズレ）
  - [ ] `splitMeshRegions` 後、**実パッチ名**を控えた（`cat constant/*/polyMesh/boundary`）
  - [ ] topoSetのbox重複による**残骸パッチ**の有無を確認（あればzeroGradientで断熱化）

### [4b] メッシュ依存の設定
- **目的**: §5の実測値を反映した設定を書く
- **成果物**: changeDictionaryDict（各領域）／底面 topoSetDict+createPatchDict／decomposeParDict
- **ゲート**:
  - [ ] changeDictは **全パッチを明示列挙**（`.*` と個別パターンの併用は `.*` が勝ち他を無視）。multiRegionHeater準拠
  - [ ] カップリングBCは `compressible::turbulentTemperatureRadCoupledMixed`（旧 `...CoupledBaffleMixed` は不可）
  - [ ] 界面熱抵抗（thicknessLayers/kappaLayers）は**両側のパッチに**設定
  - [ ] kappaLayers の単位は **W/mK**（桁違いは界面が断熱壁化する）
  - [ ] 底面 boxToFace のZ範囲は **実Z座標 ±0.011mm**
  - [ ] decomposeParDict は **global と全領域分が一致**（numberOfSubdomains）

### [6] ソルバ実行
- **目的**: 計算を回す（並列既定 `-np 4`, scotch）
- **成果物**: `log.chtMultiRegionFoam`（tee必須）＋ 時刻フィールド
- **ゲート**: §4の検証3点（6a/6b）参照

### [8] ParaView / VTK（ブランチB）
- **目的**: 温度分布・放熱経路・メッシュの目視確認
- **ゲート**:
  - [ ] マルチリージョンは `paraFoam -builtin` か `foamToVTK`（特殊文字フィールドで paraFoam 直読みが失敗する場合は VTK 経由）

### [9a] Zth(t) 抽出（ブランチA）
- **目的**: ログの Min/max T から Zth(t) を出す（`zth_calc.py`）
- **成果物**: `zth_data.csv`（列 time_s, Tj_K, Zth_KW、対数等間隔）
- **ゲート**:
  - [ ] **name-anchored 領域同定**（`Solving for ... region <name>` を追って接合温度を取る。実logの正規表現をgrepで確認）
  - [ ] **対数等間隔サンプリング**（各decadeに十分点。線形1ms間引きは禁止）
  - [ ] 最終Zth ≈ 検証2の定常Zth

### [9b] 構造関数（PyRth）
- **目的**: Zth(t) → 累積/微分構造関数（層の熱容量・熱抵抗の対応づけ）
- **成果物**: `cumul_struc.csv` / `diff_struc.csv`（PyRth、`struc_method="lanczos"`）
- **ゲート**:
  - [ ] `input_mode="impedance"` でZth直接投入、`standard_module` 完走
  - [ ] **Rcum最大 ≈ Zth_∞**（9a最終／検証2と3点自己整合）
  - [ ] 微分ピーク/累積の傾き変化が既知の層境界に対応

### [7] 最終妥当性検証
- **目的**: 物理的に正しいかを定量判定
- **ゲート**:
  - [ ] **エネルギー収支**: 発熱W ≈ 底面熱流束（積分）で閉じる
  - [ ] **定常Zth** が §2 の予測値と整合（目標: 誤差数%以内）
  - [ ] **拡がり抵抗**でCFDと1Dの差が説明できる
  - [ ] **T3Ster実測** Zth(t) / 構造関数と帯域ごとに照合（例: ceramic層は5〜100ms帯）

---

## 3. 設定ファイルの2波構成（最重要）

設定(4)を一塊にすると、底面座標・パッチ名・ワイルドカード上書きのバグが再発する。理由は**一部の設定はメッシュ出力を見ないと書けない**から。

| 波 | 内容 | 書くタイミング | メッシュ依存 |
|---|---|---|---|
| **4a** | blockMeshDict / snappyHexMeshDict / surfaceFeatureExtractDict / topoSetDict(cellZone) / meshQualityDict | 5の**前** | なし |
| **4b** | changeDictionaryDict / 底面 topoSetDict+createPatchDict / decomposeParDict | 5(checkMesh)の**後** | あり |

```
4a ──► 5 (生成 + checkMesh) ──► 4b ──► 6
              │                  ▲
              └── 実Z座標・実パッチ名 ──┘  (フィードバック)
```

**4bを書く前の固定確認**:
```bash
cat constant/*/polyMesh/boundary                 # 実パッチ名
checkMesh -region <底面領域> | grep "bounding box" # 実底面Z座標
```

---

## 4. 検証の3点分散

完走後にまとめて検証すると、設定ミスで長時間（例: 9.5h）を捨てる。**起動数秒で弾けるものは弾く**。

| 検査点 | タイミング | 見るもの | 弾けるミス例 |
|---|---|---|---|
| **6a 起動時sanity** | 起動〜数秒 | `selected N cell(s)`（発熱cell数）／fvOptions読込／全領域メッシュ読込／起動時Min/max T | 発熱層の取り違え、fvOptions無効、領域欠落 |
| **6b 計算中monitoring** | 実行中 | h残差低下／Min/max T が物理的／ΔT非崩壊 | 発散、ΔT崩壊、断熱漏れ |
| **7 完走後validation** | 完走後 | エネルギー収支／定常Zth vs 予測／拡がり抵抗／構造関数の層対応／T3Ster照合 | 設定は通るが物理が違う |

---

## 5. アウトプットが強制する設定

ステップ2で出力を決めたら、機械的に下表で設定を確定する。

| 欲しいアウトプット | 強制される設定 |
|---|---|
| **Zth(t) 過渡** | `ddtSchemes Euler`（`steadyState`不可）／writeIntervalを細かく／Min/max Tをログ出力／endTime ≥ 最大熱時定数×3〜5 |
| **定常Zth・Rth** | エネルギーが閉じる境界（側面zeroGradient＋底面fixedValue） |
| **構造関数** | Zth(t)が対数時間で十分密（PyRth `input_mode="impedance"` へ。早期µs-ms帯が要） |
| **界面熱抵抗の影響** | `thicknessLayers`/`kappaLayers` を**両側**に、kappaLayersは**W/mK** |
| **温度分布・放熱経路（B）** | writeInterval 妥当、`paraFoam -builtin` か `foamToVTK` |

固体のみCHTで毎回必要になる必須項目（出力に依らず）:
- `regionProperties` に `fluid ()`（空でも必須）
- `fvSolution` に `h` と `hFinal` ソルバ
- `0.orig` に `p`（固体のみでも必須）
- 各領域に `system/<region>/decomposeParDict`（並列時）

---

## 6. 出力のA/B分岐

ソルバ完走後にフォークする。**両者は独立**。

| | ブランチA（ログ駆動） | ブランチB（フィールド駆動） |
|---|---|---|
| 入力 | `log.chtMultiRegionFoam` の Min/max T | 時刻フィールド（`constant/<region>/polyMesh` + 各時刻） |
| 経路 | 9a Zth(t)抽出 → 9b 構造関数 | 8 foamToVTK / paraFoam → 温度分布・放熱経路 |
| ツール | `zth_calc.py`, PyRth(`standard_module`) | ParaView |
| ParaView | **不要** | 必須 |

最終照合（T3Ster実測 vs 構造関数）は **9bまで出てから**。したがって検証の重い部分は8より後ろに来る（線形手順書の「7→8→9」とは逆）。

---

## 7. 他プロジェクトへの転用（差分ポイント）

骨格は不変。ステップ1が変わると下流のどこが変わるかの対応表。

| 変わる前提 | 影響を受けるステップ |
|---|---|
| 流体領域が入る（自然対流/強制対流） | regionProperties に fluid名／0.origに U, p_rgh, (k, ε)／重力 g／turbulenceProperties／ソルバ系（buoyant…）／6bでΔtが流速ベース制約に |
| 定常解析でよい（例: 室内エアコン気流） | `ddtSchemes steadyState`／simple系ソルバ＋緩和係数＋residualControl／**ブランチA(9a/9b)は不要**（Zth/構造関数なし、PyRthも使わない）、目的関数（例: 居住域温度の標準偏差）に置換 |
| パラメトリックスイープ | 0'のコピー＋Allrun_calc 系で多ケース化／2の出力定義に「目的関数」を追加 |
| 形状が非直方体 | 3でsurfaceFeatureExtract必要／4aのrefinement設計が重くなる |

**不変なもの**: 2波構成、検証3点分散、A/B分岐、ゲートの考え方そのもの。

---

## 8. 凝縮チェックリスト（コピペ用）

```
[1] 問題定義   □ τ_max→endTime  □ 境界でエネルギーが閉じる
[2] 出力定義   □ 予測定常Zth手計算  □ 出力→強制設定 洗い出し
[3] STL        □ 全closed  □ 隣接Z一致0.01mm  □ 薄層処理
[0'] 初期化    □ foamCleanTutorials（rm -rf 禁止）
[4a] 生成系設定 □ scale スカラー  □ locationsInMesh はm  □ cellZone手段確定
[5] メッシュ    □ cellZone数=領域数  □ bbox全層内包  □ skew記録
               □ 実底面Z採取  □ 実パッチ名採取  □ 残骸パッチ確認
[4b] 依存設定   □ 全パッチ明示列挙  □ Rad系BC  □ 界面抵抗 両側
               □ kappaLayers=W/mK  □ 底面boxToFace=実Z±0.011mm
               □ decomposePar global+全領域一致
[6a] 起動sanity □ 発熱cell数  □ fvOptions  □ 全領域読込  □ 起動Min/maxT
[6b] 実行中     □ h残差低下  □ Min/maxT物理的  □ ΔT非崩壊
[9a] Zth抽出   □ name-anchored接合同定  □ 対数等間隔密度（線形間引き禁止）
[9b] 構造関数  □ impedanceモード  □ Rcum最大≈Zth_∞  □ lanczos  □ 層境界対応
[8] ParaView   □ -builtin or foamToVTK
[7] 最終検証   □ 収支閉  □ 定常Zth vs 予測  □ 拡がり抵抗説明  □ T3Ster照合
```

---

## 9. 手順書インデックスと関連資料

### 9.1 本ルーティンの手順書（実機検証済み）

| Step | ファイル | 内容 | 主な検証済み事項 |
|---|---|---|---|
| 4a | `OpenFOAM_procedure_4a_mesh_config.md` | メッシュ生成系設定 | 単位三重構造／level導出／locationsInMesh／cellZone決定木 |
| 5 | `OpenFOAM_procedure_5_mesh_gen.md` | メッシュ生成+採取 | checkMesh読解／実Z・実パッチ名・残骸パッチの採取表 |
| 4b | `OpenFOAM_procedure_4b_meshdep_config.md` | メッシュ依存設定 | 底面boxToFace(実Z±0.011mm)／changeDict3鉄則／界面熱抵抗t/κ検算／decomposePar一致 |
| 6 | `OpenFOAM_procedure_6_solver_run.md` | ソルバ実行 | 4大起動失敗要因／6a発熱cell数／6bΔt(Di律速) |
| 7 | `OpenFOAM_procedure_7_validation.md` | 妥当性検証 | エネルギー収支(wallHeatFlux)／予測vsCFD自己整合／拡がり抵抗／切り分け表 |
| 8 | `OpenFOAM_procedure_8_paraview.md` | ParaView(ブランチB) | 縦断面Plot Over Lineで界面温度段差＝接触抵抗 |
| 9a | `OpenFOAM_procedure_9a_zth_calc.md` | Zth抽出 | name-anchored同定／対数サンプリング（`zth_calc.py`同梱・検証済み） |
| 9b | `OpenFOAM_procedure_9b_pyrth_structure.md` | 構造関数(PyRth) | impedanceモード／lanczos／Rcum≈Zth_∞自己整合／T3Ster重ね描き |
| 契約 | `OpenFOAM_branchA_io_contract.md` | 9a/9b入出力契約 | 密度契約／PyRth API（実機確認）／3点自己整合 |

### 9.2 ステップ1〜3（本書§2 + 一般手順書でカバー）

- 問題定義[1] / 出力定義[2] / STL作成[3] は本書 §2 のゲートと、`OpenFOAM_solid_CHT_procedure.md`（STL確認コマンド・熱時定数推定等）でカバー。専用手順書は未作成（必要になれば同形式で追加可能）。

### 9.3 スクリプト

- `zth_calc.py` — 9aの実体（log→Zth, name-anchored, 対数サンプリング）。**検証済み**。
- PyRth（`pip install PyRth`）— 9bの構造関数算出。**自作 `struct_func.py` は廃止**（Foster→Cauerの不安定性をlanczos法で解消）。

### 9.4 参考資料（既存）

- `OpenFOAM_solid_CHT_procedure.md` — 固体多領域CHT新規構築の一般手順（STL〜並列計算）
- `ParaView_cheatsheet.md` — ブランチBの操作リファレンス
- `OpenFOAM_training_phase1〜phase5_3.md` — Phase別の学習・実例
- `CLAUDE_phase5_4.md` — 界面熱抵抗（はんだ/TIM）導入の設計例
  - 注: 同ファイルの底面Z座標（-0.0494→正は-0.00494）・はんだ予測値（0.120→正は1.2 K/W）は本ルーティンの手順書側で訂正済み

### 9.5 未了・今後の論点

- 9aの**実log検証**（実データ入手時に正規表現を実機合わせ）
- 9b PyRthの**本番チューニング**（log_time_size/deconv設定、接合近傍分解能）
- Phase 5-3で保留の**Δt(Di数)制約源の切り分けstudy**（[6]§6bに監視ポイント記載）
- **室内エアコン気流**への転用（定常buoyantSimpleFoam、ブランチA非使用、目的関数化）

# OpenFOAM Training - Phase 4: snappyHexMesh によるメッシュ作成

## 目的

任意の3D形状（STL/OBJファイル）からCFD用メッシュを作成できるようになる。Phase 5（電子基板CHT）で自分の形状を扱うための基盤技術。

---

## snappyHexMesh の全体像

### 3段階処理

snappyHexMesh は3つのステップで動作する:

```
入力: 1) STL/OBJファイル（形状定義）
      2) backgroundメッシュ（blockMeshで作った周辺空間）
      ↓
Step 1: castellatedMesh（階段状にメッシュをくり抜く）
      ↓
Step 2: snap（階段を滑らかな形状にスナップ）
      ↓
Step 3: addLayers（境界層メッシュを追加）
      ↓
出力: 複雑形状にフィットしたメッシュ
```

### 必要なファイル

| ファイル | 役割 |
|---|---|
| `constant/triSurface/<name>.obj` | STL/OBJ形状 |
| `constant/triSurface/<name>.eMesh` | 稜線情報（surfaceFeatureExtractで生成） |
| `constant/polyMesh/` | 背景メッシュ（blockMeshで生成） |
| `system/blockMeshDict` | 背景メッシュ定義 |
| `system/surfaceFeatureExtractDict` | 稜線抽出設定 |
| `system/snappyHexMeshDict` | snappyの全設定 |
| `system/meshQualityDict` | メッシュ品質基準 |

---

## 標準的な実行手順

### 1. STLファイルの準備

```bash
mkdir -p constant/triSurface
cp <STLファイル> constant/triSurface/
```

OpenFOAM対応形式: `.obj`, `.stl`, `.obj.gz`, `.stl.gz`

### 2. 稜線抽出 (surfaceFeatureExtract)

```bash
runApplication surfaceFeatureExtract
```

`system/surfaceFeatureExtractDict`の主要設定:

```
includedAngle  150;
```

意味: 隣接面の法線が30度以上折れ曲がる場所を稜線と判定。電子基板の部品（90度の角）はこの設定で確実に認識される。

| includedAngle | 効果 |
|---|---|
| 180 | すべての面間を稜線として登録（過剰） |
| 150 | **標準値**、30度以上の折れ曲がりを稜線 |
| 0 | 何も稜線にしない |

生成物: `constant/triSurface/<name>.eMesh`（バイナリ稜線データ）

### 3. 背景メッシュ生成 (blockMesh)

```bash
runApplication blockMesh
```

形状を内包する直方体を構造格子で切る。電子基板なら基板全体を内包する箱を作る。

注意: 背景メッシュは**意外と粗くてOK**。snappyが必要な部分だけ細分化する。motorBikeの例では1280セルの背景から最終35万セルへ。

### 4. snappyHexMesh 実行

```bash
runApplication snappyHexMesh -overwrite
```

`-overwrite` オプションで結果を `constant/polyMesh/` に直接書き込む（時刻ディレクトリ生成なし）。

実行ログ末尾の品質チェックで全項目0なら成功。

---

## snappyHexMeshDict の構造

326行の大きなファイルだが、6つのセクションで構成:

```
[Section 1] 実行フラグ
  castellatedMesh / snap / addLayers      ← どこまで実行するか

[Section 2] geometry
  ├─ STL登録 (triSurfaceMesh)
  └─ 仮想形状 (searchableBox等)

[Section 3] castellatedMeshControls       ← Step1: 階段状に削る
  ├─ maxGlobalCells           (上限)
  ├─ nCellsBetweenLevels      (バッファ層数)
  ├─ features                  (稜線情報を使う)
  ├─ refinementSurfaces       ★ 表面ごとのレベル
  ├─ refinementRegions        ★ 領域ベースのレベル
  └─ locationInMesh           ★ 残す側の指定

[Section 4] snapControls                  ← Step2: 表面に吸着
  └─ 各種反復回数

[Section 5] addLayersControls             ← Step3: 境界層追加
  ├─ layers                   ★ パッチ別の層数
  ├─ finalLayerThickness     ★ 厚さ
  └─ その他の高度パラメータ

[Section 6] meshQualityControls           ← 品質基準
  └─ #include "meshQualityDict"
```

★ が電子基板で実際に触るパラメータ。

---

## 主要セクション詳解

### geometry セクション

```
geometry
{
    motorBike.obj
    {
        type triSurfaceMesh;
        name motorBike;
    }
    refinementBox
    {
        type box;
        min  (-1.0 -0.7 0.0);
        max  ( 8.0  0.7 2.5);
    }
}
```

#### triSurfaceMesh

外部のSTL/OBJファイルから形状を読む。`name`で後の参照用エイリアスを定義。

#### 仮想形状（searchableBox等）

物理的に存在しないが「この領域の中だけ細分化」という指示に使える。

種類:
- `box`: 直方体
- `searchableSphere`: 球
- `searchableCylinder`: 円柱
- `searchableSurface`: STL等

電子基板での適用:
- 部品周辺だけ高解像度
- 発熱が激しい部品の近傍だけ特に細かく
- 流入出口は粗くして計算量削減

### castellatedMeshControls の重要パラメータ

#### `maxGlobalCells`

メッシュ全体のセル数上限。**安全弁**。設定ミスでメモリ枯渇を防ぐ。
- motorBike例: 2,000,000
- 電子基板初回: 1,000,000程度から始めるのが安全

#### `nCellsBetweenLevels`

異なる細分化レベル間のバッファ層数。

| 値 | 効果 |
|---|---|
| 1 | 隣接セルのレベル差は最大1（最小サイズ変化） |
| 3 | **標準値**、品質と効率のバランス |
| 5以上 | より滑らかだがセル数増加 |

レベル6とレベル0が直接隣接すると品質が悪化するので、`nCellsBetweenLevels 3` で段階的に変化させる。

#### `features`

```
features
(
    {
        file "motorBike.eMesh";
        level 6;
    }
);
```

surfaceFeatureExtract で生成した稜線情報を使う。「この稜線にメッシュが交差する場所はレベル6まで細分化」を指示。

これがないと稜線が丸まる。電子基板の角（IC、コネクタの直角部）も保てる。

#### `refinementSurfaces` ← **本丸**

```
refinementSurfaces
{
    motorBike
    {
        level (5 6);
        patchInfo
        {
            type wall;
            inGroups (motorBikeGroup);
        }
    }
}
```

`level (min max)` の意味:
- **min level**: 表面に交差するすべてのセルを最低この値まで細分化
- **max level**: 鋭い角ではこの値まで細分化（`resolveFeatureAngle`で判定）

`patchInfo` は snappy 実行後に生成されるパッチの種類を指定（通常 `wall`）。

#### `resolveFeatureAngle 30`

「隣接面の法線が30度以上違う」場所を「鋭い角」と判定する閾値。電子基板の90度の角は確実に認識される。

#### `refinementRegions`

```
refinementRegions
{
    refinementBox
    {
        mode inside;
        levels ((1E15 4));
    }
}
```

3つのモード:

| mode | 効果 |
|---|---|
| `inside` | ボックスの内側を細分化 |
| `outside` | ボックスの外側を細分化 |
| `distance` | 表面からの距離に応じてレベル指定 |

`distance`モードの例:
```
levels ((0.1 5) (0.5 4) (2.0 3))
```
表面から0.1m以内はレベル5、0.5m以内はレベル4、2.0m以内はレベル3。

電子基板での使い方: 部品近傍だけ細かくしたいときに `distance` モードが効果的。

#### `locationInMesh` ← **最も事故りやすい**

```
locationInMesh (3.0001 3.0001 0.43);
```

「メッシュとして残す側」を指定する1点。

snappyはSTL内側と外側の2領域を作るが、通常欲しいのは外側だけ。`locationInMesh` で残したい側の点を指定する。

#### 重要な注意

- 値は**面の上やセルの境界に乗らない**ようにわずかにずらす（`.0001` のような中途半端な値を使う）
- 内側と外側を間違えると、欲しい領域が消える事故が起きる
- 最悪: 面の上に乗るとメッシュが空になる

電子基板での標準: 「基板の上空、部品の少し上」を指定。

### snapControls

snap段階の各種反復数。**標準値で十分**で初心者は触らない:

| パラメータ | 役割 |
|---|---|
| `nSmoothPatch 3` | 表面の点を平滑化する反復数 |
| `tolerance 2.0` | 稜線への吸着距離 |
| `nSolveIter 30` | メッシュ変形の反復数 |
| `nFeatureSnapIter 10` | 稜線への吸着反復数 |
| `explicitFeatureSnap true` | eMeshファイルの稜線情報を使う（重要） |

### addLayersControls

#### 境界層メッシュの目的

物理的には:
- 流体が壁に近づくと境界層（速度勾配の急峻な薄い層）が形成される
- 普通の細分化では追いつかない解像度が必要
- 壁に平行な薄いセルを多数積む

#### 触る部分

| パラメータ | 役割 |
|---|---|
| `nSurfaceLayers` | 何層積むか |
| `finalLayerThickness` | 最外層の厚さ |
| `expansionRatio` | 厚みの増加率 |
| `featureAngle` | 角での層追加可否（90度部品なら100に上げる） |

#### `layers` セクション

```
layers
{
    "(lowerWall|motorBike).*"
    {
        nSurfaceLayers 1;
    }
}
```

正規表現でパッチ別に層数を指定。

#### `relativeSizes true`

層厚さを「絶対値（メートル）」ではなく「隣接セルサイズに対する比率」で指定。場所によってセルサイズが違うので、相対指定の方が一貫性がある。

#### 触らない部分

`featureAngle`、`slipFeatureAngle`、`maxFaceThicknessRatio`、`nLayerIter` などの高度パラメータは標準値で問題ない。

### meshQualityControls

```
meshQualityControls
{
    #include "meshQualityDict"
    nSmoothScale 4;
    errorReduction 0.75;
}
```

メッシュ品質基準。`#include` で別ファイルを読む。snappyの内部判定基準で、初心者は触らない。

実行ログ末尾の品質チェック項目はこのファイルの基準と対応:

```
non-orthogonality > 65 degrees       : 0
faces with skewness > 4              : 0
faces with concavity > 80 degrees    : 0
```

全項目0なら理想的なメッシュ。

---

## 細分化レベルとセルサイズの関係

レベル0のセルサイズを基準にすると:

| Level | 体積比 | 線形寸法比 |
|---|---|---|
| 0 | 1 | 1 |
| 1 | 1/8 | 1/2 |
| 2 | 1/64 | 1/4 |
| 3 | 1/512 | 1/8 |
| 4 | 1/4096 | 1/16 |
| 5 | 1/32768 | 1/32 |
| 6 | 1/262144 | 1/64 |

例: 背景セルサイズ 1m → レベル6 で 1.6cm 解像度

電子基板で部品サイズが10mm程度なら、背景セル100mm + レベル4〜5の細分化で部品周辺をmm級に解像できる計算になる。

---

## motorBikeケースの観察結果

### 最終メッシュ統計

- Total cells: 353,578
- Total faces: 1,107,965
- Total points: 406,167

背景1,280セルから約280倍に増加。**選択的細分化**の効果。

### 細分化レベル別分布

| Level | Cell数 | 由来 |
|---|---|---|
| 0 | 1,018 | 背景メッシュ未変化部分 |
| 1, 2, 3 | 計17,016 | バッファ層 |
| 4 | 134,895 | refinementBox内側 + バッファ |
| 5 | 23,709 | motorBike表面（min level） |
| 6 | 176,940 | motorBike表面の鋭い角 + features |

レベル6セルが最大シェアなのは、1個あたりの体積が小さいので同じ領域を埋めるのに多数必要だから。

### ParaViewでの観察

`Surface With Edges` 表示でSliceを切ると、3つのレベルが視覚的に確認できる:

1. **背景の粗いメッシュ**（外側）
2. **refinementBox内の中サイズメッシュ**（バイク周辺の長方形領域）
3. **バイク表面付近の最も細かいメッシュ**

レベル間は `nCellsBetweenLevels 3` により段階的にサイズ変化。`locationInMesh` の効果でバイク内部はメッシュなし（中空）。

---

## 設定の優先度（電子基板用）

| 優先度 | パラメータ | 触る頻度 |
|---|---|---|
| ★★★★★ | `locationInMesh` | 毎ケース必須 |
| ★★★★★ | `refinementSurfaces` の level | 毎ケース調整 |
| ★★★★ | `refinementRegions` | よく使う |
| ★★★★ | `nCellsBetweenLevels` | 大きく変えることは少ないが理解必要 |
| ★★★ | `addLayersControls`の`nSurfaceLayers`, `finalLayerThickness` | 境界層必要なケースで触る |
| ★★ | `features` + level | surfaceFeatureExtractとセット |
| ★ | `snapControls` 全般 | 問題出たら触る |
| ★ | `meshQualityControls` 全般 | 通常変更不要 |

---

## Phase 4 で身についたスキル

1. surfaceFeatureExtract による稜線抽出
2. blockMesh による背景メッシュ生成
3. snappyHexMesh の3段階処理（castellated → snap → addLayers）の実行と理解
4. snappyHexMeshDict の主要セクションの読解
5. refinementSurfaces / refinementRegions による細分化レベル設計
6. locationInMesh による領域選択
7. ParaView でのメッシュ可視化（Surface With Edges, Slice）
8. 設定値とメッシュ結果の対応関係の確認

---

## 詰まりやすいポイントとtipｓ

### locationInMesh の事故防止

- 必ず**面の上に乗らない値**を使う（小数点以下を中途半端に）
- 「外側」を確実に指定するため、背景メッシュの境界に近い座標を使うのも安全

### maxGlobalCells で安全弁

設定ミスでメモリ枯渇しないよう、上限を必ず設定する。最初は控えめに（100万〜200万）。

### 品質チェック全項目0が理想

`log.snappyHexMesh` 末尾の品質チェックで0以外の項目があれば、設定見直し。よくある対処:
- `nCellsBetweenLevels` を大きく
- `refinementSurfaces` の level を下げる
- `addLayersControls.featureAngle` を調整

### Allrun は学習段階では使わない

マスターのAllrunは並列実行 + 流体計算まで一気にやることが多い。学習段階では:
- シリアル実行
- メッシュ生成だけ
- 各ステップ手動実行

で動作を理解する。

---

## Phase 5 への接続

Phase 5 では Phase 1〜4 の全スキルを統合して **電子基板CHT** に挑む。

主な作業:
1. 電子基板の簡易STLモデル作成（または既存STL利用）
2. 背景メッシュの設計（基板を内包する直方体）
3. snappyHexMeshDict を電子基板用に書き換え
   - 部品ごとの refinementSurfaces 設定
   - 部品近傍の refinementRegions
   - locationInMesh の指定
4. マルチリージョン CHT としてケース構成
   - regionProperties で固体（部品、基板）と流体（空気、または液冷）を宣言
   - changeDictionaryDict で各領域のカップリング境界条件
   - 必要に応じて接触熱抵抗（thicknessLayers/kappaLayers）
5. chtMultiRegionFoam で実行
6. ParaView で温度分布、放熱経路を可視化
7. checkMesh、定量解析（Plot Over Line等）でメッシュ品質と物理を検証

これまでに身につけた全てのスキルを統合する最終課題。

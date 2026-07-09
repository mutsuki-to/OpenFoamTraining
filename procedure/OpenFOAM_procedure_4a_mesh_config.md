# 手順書 [4a] メッシュ生成系の設定（pre-meshウェーブ）

> 上位ルーティン `OpenFOAM_calc_routine.md` の §2[4a]・§3・§8 を展開した詳細手順書。
> 作業例はパワーデバイス模擬（6領域：chip / dbc_cu_top / dbc_ceramic / dbc_cu_bot / baseplate / heatsink、phase5-4の検証済み構成）。
> 値の導出式を併記してあるので他形状にも転用可。

---

## 0. このステップの位置づけ

**4a = メッシュ出力に依存しない設定を全部書くウェーブ。** メッシュを作る前（ステップ5の前）に確定できるファイル群を扱う。実パッチ名・実スナップZ座標に依存する設定は 4b（次の手順書）に分離する。

```
[3]STL ──► [4a]ここ ──► [5]メッシュ生成+checkMesh ──► [4b] ──► [6]
                              │                          ▲
                              └── 実Z座標・実パッチ名 ────┘
```

### 4a開始前に揃っているべき入力（ステップ1〜3の成果物）

| 入力 | 作業例の値 |
|---|---|
| 各層のZ座標範囲・X,Y範囲 | 下表「積層構造」 |
| 各層の最小厚さ | chip/cu系 0.3mm, ceramic 0.64mm, baseplate 3mm, heatsink 1mm |
| 個別STL（closed確認済み） | chip.stl, dbc_cu_top.stl, ... heatsink.stl |
| 隣接層のZ座標一致（0.01mm精度） | 確認済み |

積層構造（作業例）:
```
Z [mm]          層            X,Y範囲 [mm]   厚さ[mm]  refinement level
─────────────────────────────────────────────────────────────────
 0.30 〜  0.60  chip          ±2.5           0.30      (3 4)
 0.00 〜  0.30  dbc_cu_top    ±20            0.30      (3 4)
-0.64 〜  0.00  dbc_ceramic   ±22.5          0.64      (2 3)
-0.94 〜 -0.64  dbc_cu_bot    ±20            0.30      (3 4)
-3.94 〜 -0.94  baseplate     ±30            3.00      (2 3)
-4.94 〜 -3.94  heatsink      ±30            1.00      (2 3)
```

---

## 1. 4aで作るファイル一覧

| ファイル | 役割 | メッシュ依存 |
|---|---|---|
| `system/blockMeshDict` | 背景メッシュ（全層を内包する直方体） | なし |
| `system/snappyHexMeshDict` | STLフィット + cellZone作成（本丸） | なし |
| `system/surfaceFeatureExtractDict` | 稜線抽出（**直方体積層では不要**） | なし |
| `system/topoSetDict` | cellZone作成のフォールバック（boxToCell） | なし |
| `system/meshQualityDict` | snappyの品質基準（通常触らない） | なし |
| `system/controlDict`（最小） | **ユーティリティ実行に必須**（中身は最小でよい） | なし |
| `system/fvSchemes`（最小） | 同上 | なし |
| `system/fvSolution`（最小） | 同上 | なし |

> 注: blockMesh / snappyHexMesh / topoSet も内部で controlDict・fvSchemes・fvSolution を要求する。メッシュ段階でこれらが無いと起動エラー（phase5-1の教訓）。中身は最小でよいが**存在は必須**。

---

## 2. 【最重要の前置き】単位の三重構造

4aの事故の半分はここ。3つの場所で単位の扱いが違う。

| 場所 | 単位 | 記法 |
|---|---|---|
| `blockMeshDict` の頂点座標 | **m（SI）** で直接記述 | `scale 1;` ＋ 座標は `-0.035` 等 |
| `snappyHexMeshDict` の geometry（STL読込） | STLは**mm**で作ったので mm→m 変換 | `scale 0.001;` |
| `snappyHexMeshDict` の `locationsInMesh` | **m（SI）** | `(0.001 0.001 0.00045)` |
| `topoSetDict` の box座標 | **m（SI）** | `(-0.0025 -0.0025 0.0003)` |

**最頻出ミス**: STLの `scale 0.001` が `locationsInMesh` にも効くと誤解する。効かない。`locationsInMesh` は常にm。STLをmmで作っていても、点はmで指定する（0.45mm層中央 → `0.00045`）。

---

## 3. blockMeshDict

### 設計ルール

1. 全層を内包する直方体。水平方向に5〜10mmの余白。
2. 均一セルサイズ（背景 ≈ 2mm 推奨）。
3. `scale 1`、座標はmで直接。

### 派生式（任意形状に転用するとき）

```
背景セルサイズ Δ_bg ≈ 2mm（= 0.002 m）を基準にする
各方向の分割数 N = (上限座標 − 下限座標) / Δ_bg   ← 整数に丸める

水平: X,Y下限 = −(最大層の半幅 + 余白5mm)
      X,Y上限 = +(最大層の半幅 + 余白5mm)
鉛直: Z下限 = 最下層底面 − 余白(0.5mm程度)
      Z上限 = 最上層上面 + 余白(0.5mm程度)
```

### 作業例の値

```
最大層: baseplate/heatsink ±30mm → 余白5mm → X,Y ∈ [−35, 35]mm
最下面: heatsink底 −4.94mm → 余白 → Z下限 −5.5mm
最上面: chip上 0.60mm → 余白 → Z上限 1.1mm

分割数:
  Nx = Ny = (35−(−35))/2 = 70/2 = 35
  Nz = (1.1−(−5.5))/2 = 6.6/2 = 3.3 → 33（≈2mm均一を維持）
```

### テンプレート（作業例を埋めた形）

```cpp
scale   1;          // 座標はm。STLとは別系統

vertices
(
    (-0.035 -0.035 -0.0055)   // 0
    ( 0.035 -0.035 -0.0055)   // 1
    ( 0.035  0.035 -0.0055)   // 2
    (-0.035  0.035 -0.0055)   // 3
    (-0.035 -0.035  0.0011)   // 4
    ( 0.035 -0.035  0.0011)   // 5
    ( 0.035  0.035  0.0011)   // 6
    (-0.035  0.035  0.0011)   // 7
);

blocks
(
    hex (0 1 2 3 4 5 6 7) (35 35 33) simpleGrading (1 1 1)
);

boundary
(
    // 背景の外箱パッチ。snappy後はSTL表面パッチが主役になるので
    // ここは全面 patch / wall いずれでも可（固体のみなら未使用面が多い）
);
```

### gotcha / ゲート

- [ ] `scale` はスカラー（`scale (0.001 0.001 0.001)` は不可。ベクトル記法はエラー）
- [ ] 座標はm。mmで書くと1000倍の箱になりSTLが点に潰れる
- [ ] `blockMesh` 完走 → `checkMesh` で背景bounding boxが全層を内包するか確認

---

## 4. snappyHexMeshDict（本丸）

6セクション構成。★が毎回触る箇所。

```
[1] 実行フラグ        castellatedMesh / snap / addLayers
[2] geometry          STL登録 ★
[3] castellatedMeshControls
      ├ maxGlobalCells          (安全弁)
      ├ nCellsBetweenLevels
      ├ features                (直方体は空) 
      ├ refinementSurfaces ★    (層ごとのlevel)
      ├ refinementRegions
      └ locationsInMesh ★       (cellZone作成・最事故箇所)
[4] snapControls       (標準値)
[5] addLayersControls  (固体CHTは addLayers false で最小)
[6] meshQualityControls #include meshQualityDict
```

### [1] 実行フラグ

固体CHT（境界層メッシュ不要）なので addLayers は false。

```cpp
castellatedMesh true;
snap            true;
addLayers       false;   // 固体内に境界層は不要
```

### [2] geometry

各STLを `triSurfaceMesh` で登録。**STLは mm で作ったので `scale 0.001`**。

```cpp
geometry
{
    chip.stl        { type triSurfaceMesh; name chip;        scale 0.001; }
    dbc_cu_top.stl  { type triSurfaceMesh; name dbc_cu_top;  scale 0.001; }
    dbc_ceramic.stl { type triSurfaceMesh; name dbc_ceramic; scale 0.001; }
    dbc_cu_bot.stl  { type triSurfaceMesh; name dbc_cu_bot;  scale 0.001; }
    baseplate.stl   { type triSurfaceMesh; name baseplate;   scale 0.001; }
    heatsink.stl    { type triSurfaceMesh; name heatsink;    scale 0.001; }
}
```

### [3] refinementSurfaces の level 導出 ★

`level (min max)` の意味:
- **min**: 表面に交差する全セルを最低この値まで細分化
- **max**: 鋭角部（`resolveFeatureAngle`）でこの値まで

#### 導出の考え方

```
レベルL のセルサイズ = Δ_bg / 2^L
  Δ_bg = 2mm のとき：L2→0.5mm, L3→0.25mm, L4→0.125mm
```

経験則テーブル（最小厚さ → 推奨min level）:

| 層の最小厚さ | 推奨level | 厚さ方向のセル数(目安) |
|---|---|---|
| ~0.3mm | (3 4) | min3=0.25mmで約1セル + 表面付近4 |
| ~0.6mm | (2 3) | min2=0.5mmで約1セル + 3 |
| ~3mm | (2 3) | 十分 |

> **なぜ厚さ方向1セルでも許容されるか**: 薄い高熱伝導層（Cu, k=400）は厚さ方向の温度勾配がほぼ無い。律速は**横方向の拡がり熱抵抗**なので、厚さ方向の解像度より層形状とXY解像度が効く。phase5-3でこの設定が手計算と整合した実績あり。低熱伝導の厚い層（樹脂等）を扱うときは厚さ方向の解像度を上げる判断が要る。

#### 作業例

```cpp
refinementSurfaces
{
    chip        { level (3 4); }
    dbc_cu_top  { level (3 4); }
    dbc_ceramic { level (2 3); }
    dbc_cu_bot  { level (3 4); }
    baseplate   { level (2 3); }
    heatsink    { level (2 3); }
}
```

### [3] その他の castellatedMeshControls

```cpp
maxGlobalCells       2000000;   // 安全弁。想定711k(phase5-4)より十分上に
nCellsBetweenLevels  5;         // 接触積層でレベル差がある→遷移を緩やかに(非直交対策)
features             ( );       // ★直方体積層なので空。稜線抽出しない
resolveFeatureAngle  30;
allowFreeStandingZoneFaces true;  // ★cellZone作成に必須

refinementRegions { }           // 今回は領域ベース細分化なし
```

> `nCellsBetweenLevels` の一般デフォルトは3。接触積層で隣接層のlevel差（例: chip=4 と ceramic=3）があると界面の非直交性が悪化しやすいので、作業例では5でバッファを厚めにしている。

### [3] locationsInMesh ★（最事故箇所）

各層内部の1点を「この囲まれた領域を名前付きcellZoneとして残す」指示として与える。

#### 点の取り方

```
各層の点 = (x_off, y_off, z_mid)
  z_mid  = (層の上面Z + 底面Z) / 2     ← 層の中央高さ（m）
  x_off, y_off = 0.001 等の中途半端な値  ← 対称面・セル境界に乗らないため
                 ※ただし最小層(chip ±2.5mm)の内側に収まる値にする
```

#### 作業例（z_mid をmで計算）

```cpp
locationsInMesh
(
    ( (0.001 0.001  0.00045) chip)        // (0.30+0.60)/2 = 0.45mm
    ( (0.001 0.001  0.00015) dbc_cu_top)  // (0.00+0.30)/2 = 0.15mm
    ( (0.001 0.001 -0.00032) dbc_ceramic) // (-0.64+0.00)/2 = -0.32mm
    ( (0.001 0.001 -0.00079) dbc_cu_bot)  // (-0.94-0.64)/2 = -0.79mm
    ( (0.001 0.001 -0.00244) baseplate)   // (-3.94-0.94)/2 = -2.44mm
    ( (0.001 0.001 -0.00444) heatsink)    // (-4.94-3.94)/2 = -4.44mm
);
```

#### gotcha

- [ ] 単位はm。STLの `scale 0.001` はここに効かない
- [ ] 点が**面の上・セル境界に乗らない**（`.0001` 等の中途半端な値を使う）
- [ ] x_off, y_off は**最小層の内側**に収める（chip ±2.5mm なので 0.001=1mm はOK）
- [ ] 名前は geometry の `name` と一致させる（splitMeshRegionsの領域名になる）

### [4] snapControls / [5] addLayersControls / [6] meshQualityControls

snapは標準値で十分。addLayersは false なので最小。品質基準は `#include`。

```cpp
snapControls
{
    nSmoothPatch 3; tolerance 2.0; nSolveIter 30; nFeatureSnapIter 10;
    implicitFeatureSnap false; explicitFeatureSnap true; multiRegionFeatureSnap false;
}
addLayersControls
{
    relativeSizes true; layers { } expansionRatio 1.0;
    finalLayerThickness 0.3; minThickness 0.1; /* addLayers=false なので実質未使用 */
}
meshQualityControls { #include "meshQualityDict" }
mergeTolerance 1e-6;
```

### snappy実行後の品質期待値（参考、検証は5で行う）

接触する直方体積層ではsnap処理で以下が出るが、固体熱伝導では実用上許容:
```
Max non-orthogonality ≈ 82度（fvSolutionの nNonOrthogonalCorrectors 2 で対応）
Max skewness ≈ 4.0（上限をわずかに超えるが可）
```

---

## 5. surfaceFeatureExtractDict（省略判断）

**直方体積層では不要。** 理由: 稜線（features）は曲面形状で角を保つための仕組み。直方体は snappy のセル整合だけで角が出るため、`features ( )` 空で問題ない（phase5-3で実証）。

省略する場合: このファイルを作らず、snappyの `features ( )` を空にするだけ。

**作るべきケース**（転用時）: 非直方体・曲面・鋭い稜線を保持したい形状。その場合のみ `surfaceFeatureExtract` を実行し、`features ( { file "xxx.eMesh"; level L; } )` を設定。

---

## 6. cellZone作成の決定木（snappy native vs topoSet）

cellZoneの作り方は2系統ある。**primary = snappyのlocationsInMesh**、**fallback = topoSet boxToCell**。

```
snappy で locationsInMesh 設定済み
        │
        ▼ snappyHexMesh 実行（=ステップ5）
        │
   checkMesh で cellZone数を確認
        │
   ┌────┴─────────────────┐
   │ cellZone数 = 層数      │ cellZoneが空 or マージ不正
   │ かつ各zone非空         │
   ▼                        ▼
 topoSet 不要            topoSetDict(boxToCell)で作り直す
 そのまま splitMeshRegions   → §7
```

> phase5-1 では snappy の `cellZone inside` 旧記法でcellZone作成に失敗し、topoSetに切り替えた。phase5-3/5-4 では `locationsInMesh`（v2412記法、複数点）で成功している。**まずsnappy nativeで試し、checkMeshで確認してからtopoSetの要否を決める**のが手戻りが少ない。

---

## 7. topoSetDict（cellZoneフォールバック）

snappyのcellZoneが不正だった場合のみ作成。boxToCellで各層を箱で囲ってcellZone化する。

### 設計ルール（最重要：箱を重複させない）

```
各層の箱 = (層のX下限−ε, Y下限−ε, Z下限−ε)(X上限+ε, Y上限+ε, Z上限+ε)
  ε = 0.01mm = 0.00001 m  （マージン）

★ 隣接層の box上限と下限が重複しないよう、境界Z座標を厳密に一致させる
  重複すると「Cell N is multiple zones」エラー
```

### テンプレート（作業例、1層分のパターン）

```cpp
actions
(
    // ── chip （±2.5mm, Z 0.30〜0.60mm）──
    {
        name    chipCellSet;  type cellSet;  action new;
        source  boxToCell;
        box     (-0.00251 -0.00251 0.0002999) (0.00251 0.00251 0.0006001);
    }
    { name chip; type cellZoneSet; action new; source setToCellZone; set chipCellSet; }

    // ── 以下、dbc_cu_top / dbc_ceramic / dbc_cu_bot / baseplate / heatsink を
    //    同じパターンで。各層のX,Y,Z範囲を埋める。
    //    隣接層のZ境界（例: 0.0003）は両層で同じ値を使い、±εで重複させない
);
```

### gotcha / ゲート

- [ ] box座標はm
- [ ] 隣接層のZ境界値を厳密一致（chip底=cu_top上=0.0003 を共有）
- [ ] εは0.01mm（広すぎると隣接層を巻き込む、狭すぎると取りこぼす）

---

## 8. ユーティリティ用の最小 controlDict / fvSchemes / fvSolution

メッシュ生成ユーティリティを動かすためだけの最小版。**solver設定（ddt/ソルバ）は本番用を後で（4b〜6で）入れ直す**ので、ここでは最小でよい。

`system/controlDict`（最小）:
```cpp
application     chtMultiRegionFoam;
startFrom       startTime;  startTime 0;
stopAt          endTime;    endTime 1;
deltaT          1;          writeControl timeStep;  writeInterval 1;
```

`system/fvSchemes`・`system/fvSolution` は空に近い最小（`{}` で各辞書を置く）でメッシュ段階は通る。本番の中身は後段で確定。

---

## 9. 4a完了ゲート（ステップ5へ）

```
[4a] 完了チェック
  □ blockMeshDict: scaleスカラー / 座標m / 全層内包 / 均一2mm
  □ snappyHexMeshDict:
      □ geometry: 全STL scale 0.001
      □ refinementSurfaces: 各層level設定（厚さ→level導出）
      □ features ( ) 空（直方体）/ allowFreeStandingZoneFaces true
      □ locationsInMesh: 各層 z_mid（m）/ 中途半端なx,y / 名前一致
      □ addLayers false
  □ surfaceFeatureExtractDict: 直方体なら不要（作らない）
  □ topoSetDict: フォールバック用に用意（snappy成否は5で判定）
  □ meshQualityDict: 配置
  □ 最小 controlDict / fvSchemes / fvSolution: 配置（ユーティリティ起動用）
```

### ステップ5で採取し、4bへ渡す項目（このウェーブの“出口”）

4aは「メッシュ生成して実測値を採取する」5の入力。5実行後、次を必ず控える:

- cellZone数（= 層数か）
- 全層を内包するbounding box
- **実スナップ底面Z座標**（設計−4.94mm に対し実値。boxToFaceに使う）
- **実パッチ名**（`cat constant/*/polyMesh/boundary`。changeDictに使う）
- topoSet重複による残骸パッチの有無

これらが 4b（次の手順書）の入力になる。

---

## 10. 他形状への転用（差分ポイント）

| 変わる前提 | 4aで変わる箇所 |
|---|---|
| 流体領域が入る | geometry/locationsInMeshに流体領域追加、流体側はrefinement levelを流れ解像度基準で設計、addLayers検討（壁境界層） |
| 非直方体・曲面 | surfaceFeatureExtractDict必要、`features`にeMesh登録、refinementRegions(distance)を活用 |
| 大規模化 | maxGlobalCells引き上げ、背景セルを粗く+局所refinementで効率化 |
| パラメトリックスイープ（形状不変） | 4aは1回だけ。以降はメッシュ固定でAllrun_calc系へ |

**不変なもの**: 単位の三重構造、level導出の考え方、locationsInMeshの取り方、cellZone決定木、4a→5→4bのフィードバック。

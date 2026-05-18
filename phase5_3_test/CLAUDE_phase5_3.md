# OpenFOAM Phase 5-3: パワーモジュールCHT 設計仕様書

## ケース概要

- **目的**: パワーモジュール積層構造のCHT解析、Zth(t)曲線の抽出
- **ディレクトリ**: `~/OpenFOAM/training/phase5_3_powerdevice`
- **領域構成**: 固体5領域のみ（air領域なし）
- **ベースケース**: Phase 5-2から独立した新規ケース

---

## 積層構造・座標（全てmm単位、scale 0.001でm変換）

```
Z [mm]          層                X,Y範囲 [mm]    材料
─────────────────────────────────────────────────────
 0.30 〜  0.60  chip              ±2.5            Si
 0.00 〜  0.30  dbc_cu_top        ±20             Cu
-0.64 〜  0.00  dbc_ceramic       ±22.5           AlN
-0.94 〜 -0.64  dbc_cu_bot        ±20             Cu
-3.94 〜 -0.94  baseplate         ±30             Cu
─────────────────────────────────────────────────────
baseplate底面 Z=-3.94mm → fixedValue 300K + TIM
```

---

## 物性値

| 層 | 材料 | k [W/mK] | ρ [kg/m³] | Cp [J/kgK] |
|---|---|---|---|---|
| chip | Si | 148 | 2330 | 712 |
| dbc_cu_top | Cu | 400 | 8960 | 385 |
| dbc_ceramic | AlN | 170 | 3260 | 740 |
| dbc_cu_bot | Cu | 400 | 8960 | 385 |
| baseplate | Cu | 400 | 8960 | 385 |

---

## TIM設定

実測接触熱抵抗（込み）: **Rth = 2.25 cm²K/W = 2.25×10⁻⁴ m²K/W**

`thicknessLayers / kappaLayers`での表現:
```
thicknessLayers (1.0e-4);    // 0.1mm
kappaLayers     (4.444e-5);  // W/mK → Rth = 1e-4 / 4.444e-5 = 2.25e-4 m²K/W
```

設定箇所: `system/baseplate/changeDictionaryDict` の `baseplate_bottom` パッチ

---

## 発熱条件

```
領域: chip
総発熱量: 20W
設定: fvOptions scalarSemiImplicitSource, volumeMode absolute
対象フィールド: h（エンタルピー）
```

`system/chip/fvOptions`:
```cpp
heatSource
{
    type            scalarSemiImplicitSource;
    selectionMode   all;
    volumeMode      absolute;
    sources
    {
        h { explicit 20.0; implicit 0; }
    }
}
```

---

## 境界条件の全体像

### 領域間界面（splitMeshRegionsが自動生成）
全てカップリング条件 `compressible::turbulentTemperatureRadCoupledMixed`

```
chip          ↔ dbc_cu_top
dbc_cu_top    ↔ dbc_ceramic
dbc_ceramic   ↔ dbc_cu_bot
dbc_cu_bot    ↔ baseplate
```

### 外表面
| 面 | 条件 | 備考 |
|---|---|---|
| chip上面・側面 | zeroGradient | 断熱 |
| dbc_cu_top側面・上面（chip非接触部） | zeroGradient | 断熱 |
| dbc_ceramic側面 | zeroGradient | 断熱 |
| dbc_cu_bot側面 | zeroGradient | 断熱 |
| baseplate側面 | zeroGradient | 断熱 |
| **baseplate底面** | **fixedValue 300K + TIM** | コールドプレート模擬 |

エネルギー保存の確認:
```
発熱 20W = baseplate底面からの熱流束（全熱量がここへ）
側面はzeroGradient → 熱流束ゼロ
```

---

## メッシュ設計

### blockMeshDict

```
スケール: scale 0.001（mm→m）
領域: X∈[-35, 35]mm, Y∈[-35, 35]mm, Z∈[-4.5, 1.1]mm
分割: (35 35 28)
背景セルサイズ: 約2mm均一
総背景セル数: 34,300
```

### snappyHexMeshDict 細分化レベル

| STL | refinementSurfaces level | 根拠 |
|---|---|---|
| chip.stl | (3 4) | 0.3mm厚、2mm→0.25mmでレベル3 |
| dbc_cu_top.stl | (3 4) | 0.3mm厚、同上 |
| dbc_ceramic.stl | (2 3) | 0.64mm厚、2mm→0.5mmでレベル2 |
| dbc_cu_bot.stl | (3 4) | 0.3mm厚、同上 |
| baseplate.stl | (2 3) | 3mm厚、2mm→0.5mmでレベル2 |

locationInMesh: `(0.001 0.001 -2.0)` （baseplate内部、面に乗らない点）

### topoSetDict（splitMeshRegions前に実行）

boxToCellのbox座標（マージン±0.01mm込み）:

```cpp
// chip: Z∈[0.30, 0.60]mm, X,Y∈±2.5mm
box (-0.0026 -0.0026 0.00029) (0.0026 0.0026 0.00061);

// dbc_cu_top: Z∈[0.00, 0.30]mm, X,Y∈±20mm
box (-0.0201 -0.0201 -0.00001) (0.0201 0.0201 0.00031);

// dbc_ceramic: Z∈[-0.64, 0.00]mm, X,Y∈±22.5mm
box (-0.0226 -0.0226 -0.00641) (0.0226 0.0226 0.00001);

// dbc_cu_bot: Z∈[-0.94, -0.64]mm, X,Y∈±20mm
box (-0.0201 -0.0201 -0.00941) (0.0201 0.0201 -0.00639);

// baseplate: Z∈[-3.94, -0.94]mm, X,Y∈±30mm
box (-0.0301 -0.0301 -0.03941) (0.0301 0.0301 -0.00939);
```

airはなし（全セルがいずれかの固体領域）。

### baseplate底面パッチの作成（Phase 5-2と同じ手順）

splitMeshRegions後にbaseplate領域に対して実行:

```bash
topoSet -region baseplate
createPatch -region baseplate -overwrite
```

`system/baseplate/topoSetDict`:
```cpp
actions
(
    {
        name    baseplateBottomFaceSet;
        type    faceSet;
        action  new;
        source  boxToFace;
        box     (-0.0301 -0.0301 -0.039411) (0.0301 0.0301 -0.039389);
    }
);
```

`system/baseplate/createPatchDict`:
```cpp
patches
(
    {
        name          baseplate_bottom;
        patchInfo     { type wall; }
        constructFrom set;
        set           baseplateBottomFaceSet;
    }
);
```

---

## Zth抽出に向けた設定

### controlDict

```cpp
application     chtMultiRegionFoam;
startFrom       startTime;
startTime       0;
endTime         1.0;        // まず1秒で動作確認、後で延長
deltaT          1e-5;
adjustTimeStep  yes;
maxCo           0.5;
maxDi           5.0;
writeControl    adjustableRunTime;
writeInterval   0.1;        // 動作確認用、後で調整
```

**Zth曲線の時間解像度について**:
Zth(t)の初期（t<0.001s）はチップ内の熱拡散が支配的で変化が速い。
動作確認後にwriteIntervalを小さくするか、postProcessingで毎タイムステップ出力する。

### Zth(t)の計算式

```
Zth(t) = (Tj(t) - T_ref) / P

Tj(t):   chip領域の最高温度
T_ref:   300K（baseplate底面固定温度）
P:       20W
単位:    K/W
```

### postProcessing設定（system/controlDict内のfunctionsブロック）

chipの最高温度を毎タイムステップ自動出力:

```cpp
functions
{
    chipMaxT
    {
        type            volFieldValue;
        libs            (fieldFunctionObjects);
        writeControl    timeStep;
        writeInterval   1;
        operation       max;
        fields          (T);
        region          chip;
    }
}
```

出力先: `postProcessing/chipMaxT/0/volFieldValue.dat`
このファイルから時系列Tj(t)を取得し、Zth(t) = (Tj - 300) / 20 を計算する。

---

## ディレクトリ構成

```
phase5_3_powerdevice/
├── constant/
│   ├── triSurface/               ← STLファイル5つ
│   ├── regionProperties
│   ├── g
│   ├── chip/thermophysicalProperties
│   ├── dbc_cu_top/thermophysicalProperties
│   ├── dbc_ceramic/thermophysicalProperties
│   ├── dbc_cu_bot/thermophysicalProperties
│   └── baseplate/thermophysicalProperties
├── system/
│   ├── blockMeshDict
│   ├── surfaceFeatureExtractDict
│   ├── snappyHexMeshDict
│   ├── topoSetDict
│   ├── controlDict               ← functionsブロック含む
│   ├── fvSchemes
│   ├── fvSolution
│   ├── chip/
│   │   ├── changeDictionaryDict
│   │   ├── fvSchemes
│   │   ├── fvSolution
│   │   ├── fvOptions             ← 発熱項 20W
│   │   └── decomposeParDict
│   ├── dbc_cu_top/
│   ├── dbc_ceramic/
│   ├── dbc_cu_bot/
│   └── baseplate/
│       ├── changeDictionaryDict  ← baseplate_bottomにTIM+fixedValue
│       ├── topoSetDict           ← 底面faceSet定義
│       ├── createPatchDict       ← 底面パッチ作成
│       ├── fvSchemes
│       ├── fvSolution
│       └── decomposeParDict
└── 0.orig/
    └── T                         ← 固体のみなのでTのみ
```

---

## 実行手順

```bash
# 1. メッシュ生成
blockMesh
surfaceFeatureExtract
snappyHexMesh -overwrite
checkMesh

# 2. 領域分割
topoSet
splitMeshRegions -cellZones -overwrite

# 3. baseplate底面パッチ作成（splitMeshRegions後）
topoSet -region baseplate
createPatch -region baseplate -overwrite

# 4. 境界条件適用
restore0Dir
for region in chip dbc_cu_top dbc_ceramic dbc_cu_bot baseplate; do
    changeDictionary -region $region
done

# 5. 計算実行
chtMultiRegionFoam
```

---

## Phase 5-2からの主な変更点

| 項目 | Phase 5-2 | Phase 5-3 |
|---|---|---|
| 領域数 | 3（air+chip+substrate） | 5（固体のみ） |
| air領域 | あり | なし |
| 固体領域 | chip, substrate | chip, dbc_cu_top, dbc_ceramic, dbc_cu_bot, baseplate |
| TIM | なし | あり（thicknessLayers/kappaLayers） |
| 発熱量 | 0.5W | 20W |
| 目的 | 自然対流vs水冷比較 | Zth(t)曲線抽出 |
| 0.orig | T, U, p, p_rgh | Tのみ |

---

## トラブルシューティング

### topoSetでcellZoneが空になる
boxToCellのbox座標がセル中心を含んでいない可能性。
マージンを±0.01mmから±0.05mmに広げて再試行。
各cellZoneのセル数をログで確認する:
```
grep "cellZone" log.topoSet
```

### 層間でcellZoneが重複する
隣接層のboxが重なっている。Z方向の境界値を確認し、
上の層のZmax = 下の層のZminになるよう調整。

### createPatch後にbaseplate_bottomが0 faces
splitMeshRegions後のbaseplateメッシュでZ=-3.94mm面が
境界面になっているか確認:
```bash
checkMesh -region baseplate | grep -A3 "Boundary"
```

### chtMultiRegionFoamが即座にクラッシュ
固体のみ構成ではU, p_rgh, k, epsilonは不要。
0/<領域>/にこれらが存在するとエラーになる。
0.origにはTのみ配置する。

### Zth曲線の初期が荒い
postProcessingのwriteControlをtimeStepにすることで
毎タイムステップ出力できる（ファイルサイズは増えるが精度向上）。

### 計算が遅い
Cu（k=400, α=1.2e-4）はΔtを強く制約する（Phase 5-2で経験済み）。
maxDiを5.0より大きくすると速くなるが安定性とのトレードオフ。
まず短時間（endTime 0.1s）で動作確認してから延長する。

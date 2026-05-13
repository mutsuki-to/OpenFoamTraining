# OpenFOAM Training - Phase 5-2: 水冷 CHT（コールドプレート模擬）

## 目的

Phase 5-1（自然対流 CHT）のケースを土台に、substrate 底面に固定温度境界条件（コールドプレート）を追加し、水冷と自然対流の温度差を定量比較する。

- **Phase 5-1**: 自然対流のみ（chip 温度上昇 +0.6 K）
- **Phase 5-2**: substrate 底面を 300 K に固定（水冷模擬）

---

## ケース構成の概要

### 形状・物性

```
chip:      X∈[-2.5, 2.5]mm, Y∈[-2.5, 2.5]mm, Z∈[0.1, 0.4]mm  (Si、発熱体)
substrate: X∈[-15, 15]mm,   Y∈[-15, 15]mm,   Z∈[-2.0, 0.1]mm  (Cu、基板)
air:       100×100×80mm の直方体（残り全部）
重力:      (0, 0, -9.81)
```

| 物質 | 熱伝導率 k [W/mK] | 熱拡散率 α [m²/s] |
|---|---|---|
| Si (chip) | 148 | 8.9×10⁻⁵ |
| Cu (substrate) | 400 | 1.2×10⁻⁴ |
| 鉄（参考） | 80 | 2.2×10⁻⁵ |

Cu の熱拡散率は鉄の **5.3 倍**。この値が後述の計算時間増大に直結する。

---

## Phase 5-1 からの変更内容

### 変更の核心

Phase 5-1 の substrate パッチ構成:

```
substrate_to_chip   （chip とのカップリング面）
substrate_to_air    （air とのカップリング面 ← 底面・側面・上面が混在）
```

`substrate_to_air` が底面と側面を一括管理しているため、底面だけに境界条件を与えられない。これを分離して `substrate_bottom` パッチを作る。

### 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `system/substrate/topoSetDict` | 新規作成 | substrate 底面の faceSet 定義 |
| `system/substrate/createPatchDict` | 新規作成 | faceSet → パッチ変換の定義 |
| `system/substrate/changeDictionaryDict` | 追記 | substrate_bottom に fixedValue 300K |
| `Allrun.pre` | 新規作成 | メッシュ再生成スクリプト |
| `AllrunParallel` | 新規作成 | 並列計算スクリプト |
| `system/decomposeParDict` 全4ファイル | 修正 | 4 → 8 並列に変更 |

---

## 作業手順の詳細

### Step 1: Phase 5-1 からのコピー

計算結果（`processor*/`、`log.*`、`5/` 等）を除いてコピーする。

```bash
cp -r phase5_1_natural/0         phase5_2_watercooling/
cp -r phase5_1_natural/0.orig    phase5_2_watercooling/
cp -r phase5_1_natural/constant  phase5_2_watercooling/
cp -r phase5_1_natural/system    phase5_2_watercooling/
cp    phase5_1_natural/Allrun    phase5_2_watercooling/
```

### Step 2: substrate 底面の faceSet 定義（splitMeshRegions 後に実行）

`system/substrate/topoSetDict`:

```cpp
actions
(
    {
        name    substrateBotFaceSet;
        type    faceSet;
        action  new;
        source  boxToFace;
        box     (-0.0151 -0.0151 -0.002011) (0.0151 0.0151 -0.001989);
    }
);
```

**ポイント**: Z = -0.002 m（substrate 底面）を中心に ±0.011 mm の薄い箱を使い、底面の境界面だけを捕捉する。

#### なぜ「splitMeshRegions 後」に実行するか

最初はグローバルメッシュに対して topoSet + createPatch を実行しようとしたが、2 つのエラーに遭遇した:

| エラー | 原因 | 対処 |
|---|---|---|
| `faceZoneSet` で `set` キーが無効 | v2412 では `faceSet` キーが必要 | faceZone 方式を廃棄 |
| `createPatch` で `constructFrom faceZone` が無効 | v2412 の有効ソースは `patches` か `set` のみ | `constructFrom set` に変更 |

さらに根本問題として、グローバルメッシュの Z = -0.002 m 面は substrate-air 間の**内部面**であり、`createPatch` で単純にパッチ化できない。

解決策: `splitMeshRegions` 後の substrate リージョンメッシュでは Z = -0.002 m 面が**境界面**になるため、分割後に `topoSet -region substrate` → `createPatch -region substrate` を実行する。

### Step 3: createPatchDict（substrate リージョン用）

`system/substrate/createPatchDict`:

```cpp
patches
(
    {
        name            substrate_bottom;
        patchInfo { type wall; }
        constructFrom   set;
        set             substrateBotFaceSet;
    }
);
```

### Step 4: changeDictionaryDict への境界条件追加

`system/substrate/changeDictionaryDict` の `T.boundaryField` に追記:

```cpp
substrate_bottom
{
    type            fixedValue;
    value           uniform 300;
}
```

### Step 5: Allrun.pre の作成

メッシュ再生成スクリプト。**`splitMeshRegions` 後に substrate 専用の topoSet + createPatch を実行**するのがポイント:

```bash
runApplication blockMesh
runApplication surfaceFeatureExtract
runApplication snappyHexMesh -overwrite
runApplication topoSet
runApplication splitMeshRegions -cellZones -overwrite

# substrate 底面パッチを splitMeshRegions 後に作成
runApplication -s substrate topoSet -region substrate
runApplication -s substrate createPatch -region substrate -overwrite

restore0Dir
```

### Step 6: 成功確認

```bash
cat constant/substrate/polyMesh/boundary
```

```
3
(
    substrate_to_chip  { type mappedWall; nFaces 256;  ... }
    substrate_to_air   { type mappedWall; nFaces 3220; ... }  ← 5336 → 3220 に減少
    substrate_bottom   { type wall;       nFaces 2116; ... }  ← 新規
)
```

`substrate_to_air` の 5336 面が 3220（側面） + 2116（底面 = `substrate_bottom`）に分離された。

---

## 並列計算の設定

### 経緯

逐次計算で約 3 時間かかることが判明し、途中で中断して並列化した。

### マルチリージョンケースの decomposeParDict 配置

マルチリージョンケースでは `decomposePar -region <name>` が**リージョン別**の dict を読む:

```
system/decomposeParDict          ← runParallel がプロセス数を読む
system/air/decomposeParDict      ← decomposePar -region air が読む
system/chip/decomposeParDict     ← decomposePar -region chip が読む
system/substrate/decomposeParDict← decomposePar -region substrate が読む
```

**失敗した設定**: グローバルの `system/decomposeParDict` だけを 4 → 8 に変更した。  
→ `runParallel` が 8 プロセスを起動したが、各リージョンは 4 分割のまま → processor4〜7 にメッシュが存在せずクラッシュ。

**正しい対処**: 4 ファイル全て一括変更:

```bash
for f in system/decomposeParDict \
          system/air/decomposeParDict \
          system/chip/decomposeParDict \
          system/substrate/decomposeParDict; do
    sed -i 's/numberOfSubdomains 4;/numberOfSubdomains 8;/' $f
done
```

### AllrunParallel スクリプト

```bash
# 0.orig → 0/<region>/ にコピー
for region in air chip substrate; do
    rm -rf 0/$region && mkdir -p 0/$region && cp 0.orig/* 0/$region/
done

# 固体から流体専用フィールドを削除
for region in chip substrate; do
    rm -f 0/$region/U 0/$region/p_rgh
done

# 境界条件適用
for region in air chip substrate; do
    runApplication -s $region changeDictionary -region $region
done

# 各リージョンを分割
for region in air chip substrate; do
    runApplication -s $region decomposePar -region $region
done

# 並列計算
runParallel $(getApplication)

# 最終時刻の結果を統合
runApplication reconstructPar -allRegions -latestTime
```

---

## 計算時間の分析

### Phase 3 multiRegionHeater との比較

| 項目 | Phase 3 | Phase 5-2 |
|---|---|---|
| メッシュ生成 | blockMesh のみ | blockMesh + snappyHexMesh |
| 総セル数 | 約 3,000 | 約 45,236（**15 倍**） |
| 固体の熱拡散率 | 2.2×10⁻⁵ m²/s（鉄） | 1.2×10⁻⁴ m²/s（Cu、**5.3 倍**） |
| 計算時間 | 数分 | 約 3 時間 |

計算時間の差は**セル数 15 倍 × 熱拡散率による Δt 制約**の組み合わせによる。

### deltaT の経時変化

`adjustTimeStep` により Δt は自動調整されるが、流れが発達するにつれて単調に減少した:

| 計算開始 | ~100 s 経過 | ~3 時間経過 |
|---|---|---|
| 5.3×10⁻⁴ s | 4.7×10⁻⁵ s | **1.5×10⁻⁵ s**（開始時の 1/35）|

Δt が 1/35 になれば 1 タイムステップが同じ計算量でも同じ物理時間を進めるのに 35 ステップ必要になる。コア数を増やしても Δt の縮小は防げない。

**Δt を制約する式（Diffusion Number）**:

```
Di = α × Δt / Δx²  ≤  maxDi（= 5.0）
→  Δt ≤ maxDi × Δx² / α
```

α が大きい（Cu）ほど Δt の上限が小さくなる。

### 並列化効果

| 設定 | 速度 [sim-s/real-s] | 備考 |
|---|---|---|
| 逐次（1 core） | 約 0.00084 | 計算途中で中断 |
| 並列（8 cores） | 約 0.00027 | 速度約 3 倍 |

並列化で 3 倍の高速化を得たが、Δt の縮小が続いたため合計 3 時間かかった。

---

## 計算結果

### 最終温度（Time = 5.0 s）

| 領域 | Min T [K] | Max T [K] | 上昇量 |
|---|---|---|---|
| air | 299.998 | 300.11 | +0.11 K |
| chip | 300.038 | 300.11 | **+0.11 K** |
| substrate | 300.000 | 300.082 | +0.082 K |

### Phase 5-1 との比較

| | Phase 5-1（自然対流） | Phase 5-2（水冷） |
|---|---|---|
| chip 最高温度上昇 | **+0.6 K** | **+0.11 K** |
| 冷却改善率 | ベースライン | **約 5.5 倍** |

Cu 基板（k = 400 W/mK）が固定温度コールドプレートと chip の間で高効率の熱経路を形成し、chip の温度上昇を 1/5 以下に抑えた。

---

## Phase 5-2 で身についたスキル

1. **マルチリージョン CHT への境界条件追加**  
   既存パッチを分割して新パッチを作る設計フロー

2. **splitMeshRegions 前後でのメッシュ操作の違い**  
   グローバルメッシュの内部面はリージョン分割後に初めて境界面になる

3. **OpenFOAM v2412 の createPatch 制約**  
   `constructFrom faceZone` は非対応。`constructFrom set` + `topoSetDict` の組み合わせが正しい

4. **マルチリージョンケースの decomposeParDict 配置**  
   グローバルとリージョン別の 4 ファイル全てを一致させる必要がある

5. **Diffusion Number による Δt 制約の理解**  
   高熱伝導材料（Cu）は Δt を小さくし、計算時間を伸ばす直接原因になる

6. **計算時間の構造的理解**  
   セル数・物性・タイムステップの3要因が乗算的に計算コストを決める

---

## 詰まりやすいポイントと Tips

### createPatch の構文（v2412）

```cpp
// NG: faceZone は v2412 では無効
constructFrom   faceZone;
faceZone        substrateBotZone;

// OK: set（faceSet）を使う
constructFrom   set;
set             substrateBotFaceSet;
```

### topoSet の faceZoneSet で使うキー名

```cpp
// NG: set
source  setToFaceZone;
set     substrateBotFaceSet;

// OK: faceSet
source  setToFaceZone;
faceSet substrateBotFaceSet;
```

ただし Phase 5-2 ではグローバルメッシュでの faceZone 方式自体を廃棄し、分割後リージョンに対して直接 faceSet を使う方針に変更した。

### boxToFace の厚みは ±0.011 mm が目安

```cpp
box  (-0.0151 -0.0151 -0.002011) (0.0151 0.0151 -0.001989);
//                                         ↑             ↑
//                              Z=-0.002 ± 0.011 mm
```

メッシュのセル境界に乗らないよう微小にずらす。厚みが広すぎると隣接面も取り込む。

### 並列計算は AllrunParallel を使う

通常の Allrun は逐次計算前提（`changeDictionary → chtMultiRegionFoam`）。  
並列計算では `decomposePar → mpirun → reconstructPar` の順序が必要なため、別スクリプトに分けると管理しやすい。

---

## Phase 5-2 から先への接続

今回のコールドプレートは「固定温度 300 K」という最もシンプルな水冷モデル。より現実的な拡張として以下が考えられる:

- **強制対流水冷**: 水の流れを直接シミュレーションするには water リージョンを追加し、流速・流量・入口温度を境界条件として設定する（3 流体・2 固体の 5 リージョン CHT）
- **接触熱抵抗**: chip-substrate 間に TIM（Thermal Interface Material）を模擬するため `thicknessLayers` / `kappaLayers` を追加する
- **過渡応答**: 現状は定常収束を待つ非定常計算。パルス発熱への応答や起動過渡をみる場合も同じ構成で実施できる

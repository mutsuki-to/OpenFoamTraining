# CLAUDE.md — OpenFOAM Phase 5-2: 水冷CHT（コールドプレート模擬）

## タスク概要

Phase 5-1（自然対流CHT）のケースを複製し、substrateの底面に固定温度境界条件（コールドプレート模擬）を追加した水冷CHTケースを構築する。

**目的**: 自然対流（Phase 5-1）と水冷（Phase 5-2）の定量的温度比較

---

## 前提・環境

- OpenFOAM v2412 (WSL2 Ubuntu)
- 作業ベースディレクトリ: `~/OpenFOAM/training/`
- コピー元: `phase5_1_natural/`
- 作成先: `phase5_2_watercooling/`

---

## Phase 5-1 ケース構成の把握（変更前の状態）

### 形状・座標系

```
chip:      X∈[-2.5, 2.5]mm, Y∈[-2.5, 2.5]mm, Z∈[0.1, 0.4]mm  (Si, 発熱体)
substrate: X∈[-15, 15]mm,   Y∈[-15, 15]mm,   Z∈[-2.0, 0.1]mm  (Cu, 基板)
air:       100×100×80mm の直方体（残り全部）
重力: (0, 0, -9.81)  ← Z軸下方向
```

### 現状のsubstrateパッチ（変更前）

```
substrate_to_chip   （chipとのカップリング面）
substrate_to_air    （airとのカップリング面 ← 底面・側面・上面が混在）
```

**問題**: substrate底面が`substrate_to_air`に含まれており、底面だけに独立した境界条件を与えられない。

### 変更方針

`topoSetDict`でsubstrate底面のfaceZoneを追加 → `createPatchDict`でパッチ化 → substrateの`changeDictionaryDict`で底面にfixedValue 300Kを設定。

---

## 作業手順

### Step 1: ケースのコピー

```bash
cd ~/OpenFOAM/training
cp -r phase5_1_natural phase5_2_watercooling
cd phase5_2_watercooling
```

### Step 2: topoSetDict の修正

`system/topoSetDict` の末尾（airのcellZoneSet定義の後）に以下を**追加**する。

```cpp
    // ============================================================
    // substrate底面 faceZone
    // substrate底面: Z = -0.002m の面
    // X∈[-15, 15]mm, Y∈[-15, 15]mm
    // ============================================================
    {
        name    substrateBotFaceSet;
        type    faceSet;
        action  new;
        source  boxToFace;
        box     (-0.0151 -0.0151 -0.002011) (0.0151 0.0151 -0.001989);
    }
    {
        name    substrateBotZone;
        type    faceZoneSet;
        action  new;
        source  setToFaceZone;
        set     substrateBotFaceSet;
    }
```

**注意**: boxの厚みを±0.011mm（0.000011m）にしてZ=-0.002mの面だけを捕捉する。セル境界に乗らないよう微小にずらしている。

### Step 3: createPatchDict の新規作成

`system/createPatchDict` を以下の内容で新規作成する。

```cpp
/*--------------------------------*- C++ -*----------------------------------*\
| =========                 |                                                 |
| \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\    /   O peration     | Version:  v2412                                 |
\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      createPatchDict;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

pointSync false;

patches
(
    {
        name            substrate_bottom;
        patchInfo
        {
            type            wall;
        }
        constructFrom   faceZone;
        faceZone        substrateBotZone;
    }
);
// ************************************************************************* //
```

### Step 4: Allrun.pre の修正

`Allrun.pre` を開き、`topoSet` の実行行の**直後**に `createPatch` を追加する。

変更前:
```bash
runApplication topoSet
restore0Dir
runApplication splitMeshRegions -cellZones -overwrite
```

変更後:
```bash
runApplication topoSet
runApplication createPatch -overwrite
restore0Dir
runApplication splitMeshRegions -cellZones -overwrite
```

### Step 5: system/substrate/changeDictionaryDict の修正

`system/substrate/changeDictionaryDict` の `T` の `boundaryField` セクションに `substrate_bottom` エントリを**追加**する。

追加する内容:
```cpp
        substrate_bottom
        {
            type            fixedValue;
            value           uniform 300;
        }
```

既存の `substrate_to_chip` と `substrate_to_air` のエントリはそのまま残す。

### Step 6: 動作確認

以下の順で実行し、各ステップのログを確認する。

```bash
# メッシュ再生成
./Allrun.pre

# substrate_bottomパッチが作成されたか確認
cat constant/substrate/polyMesh/boundary | grep -A5 substrate_bottom

# CHT計算実行
runApplication chtMultiRegionFoam
```

---

## 期待される結果

### substrateのboundaryファイル（成功時）

```
3
(
    substrate_to_chip   { type mappedWall; ... }
    substrate_to_air    { type mappedWall; ... }
    substrate_bottom    { type wall; ... }       ← 新規追加
)
```

### 物理的予測

| 領域 | Phase 5-1 (自然対流) | Phase 5-2 (水冷) |
|---|---|---|
| chip温度上昇 | ~0.6 K | << 0.6 K（大幅低下を期待） |
| substrate温度分布 | 全体的に上昇 | 底面付近で300Kに近づく |

コールドプレート（fixedValue 300K）はCu基板（k=400 W/mK）を通じて圧倒的に効率よくchipを冷却するため、chip温度上昇は大幅に減少するはず。

---

## トラブルシューティング

### substrateBotFaceSetが0 facesになる場合

背景メッシュのセル境界とZ=-0.002mの位置がずれている可能性がある。以下で確認:

```bash
checkMesh | grep "Bounding box"
```

背景メッシュの実際のZ最小座標を確認し、`topoSetDict`のboxZ範囲を調整する。

### createPatch後もsubstrate_bottomが現れない場合

`splitMeshRegions`の前に`createPatch`が実行されているか確認。また`topoSetDict`のfaceZone定義でboxの厚みが適切か（面の両側±0.01mm程度）を確認する。

### changeDictionaryでsubstrate_bottomが「boundary not found」になる場合

`splitMeshRegions`後に`substrate_bottom`パッチが存在するかを先に確認:
```bash
cat constant/substrate/polyMesh/boundary
```

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `system/topoSetDict` | 追記 | substrate底面のfaceZone定義を追加 |
| `system/createPatchDict` | 新規作成 | faceZone→パッチ変換の定義 |
| `Allrun.pre` | 修正 | topoSet後にcreatePathを追加 |
| `system/substrate/changeDictionaryDict` | 追記 | substrate_bottomにfixedValue 300K |

---

## 完了条件

1. `constant/substrate/polyMesh/boundary` に `substrate_bottom` パッチが存在する
2. `chtMultiRegionFoam` が正常に実行・収束する
3. ParaViewでsubstrate底面が300Kに固定されていることを確認
4. chip温度がPhase 5-1より低いことを確認

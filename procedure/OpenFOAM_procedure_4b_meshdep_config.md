# 手順書 [4b] メッシュ依存の設定（post-meshウェーブ）

> 上位ルーティン `OpenFOAM_calc_routine.md` の §2[4b]・§3 を展開した詳細手順書。
> 手順書[5]の**採取表（④実Z・⑤実パッチ名・⑥残骸パッチ）を消費**して、メッシュ依存の設定を書く。
> 作業例はパワーデバイス模擬（6領域、はんだ＋TIMの界面熱抵抗あり、phase5-4構成）。

---

## 0. このステップの位置づけ

**4b = §5で採取した実測値を反映して設定を書くウェーブ。** 設計値ではなく**実スナップ値**を使うのが本質。ここを設計値で書くと `Read 0 faces from faceSet` / `boundary not found` で詰まる。

```
[4a]設定 ──► [5]生成+採取 ──► [4b]ここ ──► [6]実行
                 採取表 ─────────┘
```

### 4b開始前に揃っているべき入力（§5の採取表）

| 採取項目 | 4bでの用途 | 作業例の値 |
|---|---|---|
| ④ 実スナップ底面Z | Part A の boxToFace Z範囲 | heatsink底 実 −0.004948 m |
| ⑤ 実パッチ名 | Part B の changeDict 列挙 | `chip`, `chip_to_dbc_cu_top`, … |
| ⑥ 残骸パッチ | Part B で zeroGradient化 | dbc_cu_bot に dbc_ceramic残留 等 |

---

## 1. 4bで作る/実行するもの

| 区分 | 成果物 | このウェーブで | 消費する採取 |
|---|---|---|---|
| **Part A** 底面パッチ | `system/<底面領域>/topoSetDict` + `createPatchDict` | **書く＋実行**（メッシュ操作） | ④ |
| **Part B** 境界条件 | `system/<各領域>/changeDictionaryDict` | 書く（適用は[6]） | ⑤⑥ |
| **Part C** 並列分割 | `system/decomposeParDict` + `system/<各領域>/decomposeParDict` | 書く（実行は[6]） | — |

> Part Aだけは**この場でメッシュを変更する**（新パッチ追加）。Part B（changeDict適用）とPart C（decomposePar実行）は[6]の実行直前に走らせる。

---

## 2. Part A: 底面パッチ作成

`splitMeshRegions` 直後、底面fixedValueを与える領域（作業例: heatsink）の外表面パッチ `<region>` には、側面と底面が**混在**している。底面だけを切り出して `<region>_bottom` を作る。

### A-1. system/heatsink/topoSetDict（boxToFace）

**採取④の実Z（−0.004948 m）± 0.011mm** でZ範囲を切る。

```cpp
actions
(
    {
        name    heatsinkBottomFaceSet;
        type    faceSet;
        action  new;
        source  boxToFace;
        // X,Y: heatsink ±30mm に余白。Z: 実底面 −0.004948 ± 0.000011
        box     (-0.0301 -0.0301 -0.004959) (0.0301 0.0301 -0.004937);
    }
);
```

**★桁の検算（このウェーブ最重要）**:
```
heatsink底面 = −4.94mm = −0.00494 m （オーダー e-3）
  桁を1つ落として −0.0494 と書くと −49.4mm → faceSet空（Read 0 faces）
採取④の実値 −0.004948 で必ず検算してから書く
```

### A-2. system/heatsink/createPatchDict

```cpp
patches
(
    {
        name          heatsink_bottom;
        patchInfo     { type wall; }
        constructFrom set;          // v2412: faceZone不可、setを使う
        set           heatsinkBottomFaceSet;
    }
);
```

### A-3. 実行

```bash
topoSet      -region heatsink     # system/heatsink/topoSetDict を読む
createPatch  -region heatsink -overwrite   # system/heatsink/createPatchDict を読む
```

### A-4. 検証（その場で必ず）

```bash
cat constant/heatsink/polyMesh/boundary
```
```
heatsink_bottom { type wall; nFaces 3600; ... }   ← nFaces > 0 で存在すること
```

- [ ] `heatsink_bottom` が **nFaces > 0** で生成された
- [ ] nFaces=0 なら → boxToFaceのZ範囲が実底面からズレている（採取④を再確認、§5へ戻る）

---

## 3. Part B: changeDictionaryDict（各領域）

テンプレート `0.orig/T`（`".*"` で全境界zeroGradient）を、領域ごとに**実際の境界条件で上書き**する。

### B-0. 鉄則3つ

1. **全パッチを明示列挙する。`".*"` と個別パッチを併用しない。**
   併用すると `".*"` だけが効き個別指定が無視される（phase5-1の暴走バグ）。
   > 補足: `0.orig/T` 側の `".*"` テンプレートはOK（changeDictで上書きされる前提）。**changeDict内**で混ぜるのが禁止。
2. カップリングBCは `compressible::turbulentTemperatureRadCoupledMixed`（旧 `...turbulentTemperatureCoupledBaffleMixed` は不可）。
3. 界面熱抵抗（thicknessLayers/kappaLayers）は**界面の両側パッチに同じ値**を書く。

### B-1. 界面熱抵抗の値と検算

`接触熱抵抗 Rth[m²K/W] = thicknessLayers / kappaLayers`

| 界面 | Rth意図 | thicknessLayers [m] | kappaLayers [W/mK] | 検算 t/κ [m²K/W] |
|---|---|---|---|---|
| はんだ chip↔dbc_cu_top | 0.3 cm²K/W = 3.0e-5 | 1.0e-4 | 3.333e-4 | 1e-4/3.333e-4 = **3.0e-5** ✓ |
| TIM baseplate↔heatsink | 2.25 cm²K/W = 2.25e-4 | 1.0e-4 | 4.444e-5 | 1e-4/4.444e-5 = **2.25e-4** ✓ |

**★kappaLayersの単位ミスは静かで致命的**: kappaLayers は W/mK。桁を1万倍間違えると界面が**断熱壁化**して、エラーも出ずにZthが激変する。書いたら必ず `t/κ` を手計算して意図した m²K/W に一致するか確認する。

**面積換算での効き具合（step2/step7の物差し、ここでのsanity）**:
```
Rth[K/W] = Rth[m²K/W] / 接触面積A[m²]
  はんだ: 3.0e-5 / 25e-6  (chip 5×5mm)   = 1.2  K/W   ← 小面積で支配的
  TIM   : 2.25e-4 / 3600e-6 (baseplate)  = 0.063 K/W   ← 大面積で相対的に小
```
材料Rthは TIM(2.25) > はんだ(0.3) [cm²K/W] だが、**面積差（144倍）で逆転**し、小面積のはんだがK/Wでは支配的になる。界面熱抵抗を入れるときは「材料Rthではなく面積で割ったK/Wで効き具合を判断する」。

### B-2. テンプレート（領域別、採取⑤の実パッチ名を列挙）

**chip**（外表面 + はんだ界面）:
```cpp
dictionaryReplacement
{
    T
    {
        internalField   uniform 300;
        boundaryField
        {
            chip                                  // 外表面（上面・側面）
            {
                type    zeroGradient;
                value   uniform 300;
            }
            chip_to_dbc_cu_top                    // はんだ界面（両側に熱抵抗）
            {
                type            compressible::turbulentTemperatureRadCoupledMixed;
                Tnbr            T;
                kappaMethod     solidThermo;
                thicknessLayers (1.0e-4);
                kappaLayers     (3.333e-4);
                value           uniform 300;
            }
        }
    }
}
```

**dbc_cu_top**（はんだ界面の反対側 + 抵抗なし界面）:
```cpp
dbc_cu_top              { type zeroGradient; value uniform 300; }

dbc_cu_top_to_chip                                 // はんだ（反対側、同じ値）
{
    type compressible::turbulentTemperatureRadCoupledMixed;
    Tnbr T; kappaMethod solidThermo;
    thicknessLayers (1.0e-4); kappaLayers (3.333e-4);
    value uniform 300;
}
dbc_cu_top_to_dbc_ceramic                          // 抵抗なし界面
{
    type compressible::turbulentTemperatureRadCoupledMixed;
    Tnbr T; kappaMethod solidThermo;
    value uniform 300;
}
```

**baseplate**（抵抗なし界面 + TIM界面、底面fixedValueは無し＝heatsinkへ移譲）:
```cpp
baseplate               { type zeroGradient; value uniform 300; }

baseplate_to_dbc_cu_bot                            // 抵抗なし
{
    type compressible::turbulentTemperatureRadCoupledMixed;
    Tnbr T; kappaMethod solidThermo;
    value uniform 300;
}
baseplate_to_heatsink                              // TIM（両側に熱抵抗）
{
    type compressible::turbulentTemperatureRadCoupledMixed;
    Tnbr T; kappaMethod solidThermo;
    thicknessLayers (1.0e-4); kappaLayers (4.444e-5);
    value uniform 300;
}
```

**heatsink**（TIM界面の反対側 + 底面fixedValue）:
```cpp
heatsink                { type zeroGradient; value uniform 300; }

heatsink_to_baseplate                              // TIM（反対側、同じ値）
{
    type compressible::turbulentTemperatureRadCoupledMixed;
    Tnbr T; kappaMethod solidThermo;
    thicknessLayers (1.0e-4); kappaLayers (4.444e-5);
    value uniform 300;
}
heatsink_bottom                                    // コールドプレート
{
    type    fixedValue;
    value   uniform 300;
}
```

**dbc_ceramic / dbc_cu_bot** も同様に、外表面zeroGradient + 各界面カップリング（抵抗なし）を**実パッチ名で列挙**。

### B-3. 残骸パッチの処理（採取⑥）

§5で検出した残骸パッチ（例: dbc_cu_bot 領域に残る `dbc_ceramic`）は、その領域の changeDict に **zeroGradient（断熱）** で追加して無害化する。

```cpp
// dbc_cu_bot/changeDictionaryDict の boundaryField に追記
dbc_ceramic             { type zeroGradient; value uniform 300; }   // 残骸→断熱
```

### B-4. 検証（書いた直後の机上チェック）

- [ ] 各領域で `cat constant/<region>/polyMesh/boundary` の**全パッチ**が changeDict に登場する（漏れ＝起動時 `boundary not found` or 未上書き）
- [ ] `".*"` を個別パッチと併用していない
- [ ] カップリングBC名が `...RadCoupledMixed`
- [ ] 熱抵抗界面は**両側**に thicknessLayers/kappaLayers、`t/κ` 検算済み
- [ ] 底面は fixedValue、残骸は zeroGradient

> 実際に効いたかの最終確認は[6a]（`0/<region>/T` の中身確認・起動時Min/maxT）で行う。

---

## 4. Part C: decomposeParDict（並列分割）

### C-0. 鉄則: global と全領域分の `numberOfSubdomains` を一致させる

phase5-2の事故: globalだけ 4→8 に変え、領域別が4のまま → processor4〜7が空 → クラッシュ。**global + 領域別すべてを一致**させる。

### C-1. コア数の決定

```
i5-1335U: 物理コア 4 → 実用上のスロット上限 4
→ numberOfSubdomains 4 / method scotch
  （-np 4 とdecomposeParの分割数を一致させる。オーバーサブスクライブは避ける）
```

### C-2. 配置（global + 領域別）

```bash
# 領域別
for region in chip dbc_cu_top dbc_ceramic dbc_cu_bot baseplate heatsink; do
    cat > system/$region/decomposeParDict << 'DICT'
numberOfSubdomains 4;
method scotch;
DICT
done

# global（runParallelがプロセス数を読む）
cp system/heatsink/decomposeParDict system/decomposeParDict
```

decomposeParDict の中身:
```cpp
numberOfSubdomains 4;
method             scotch;
```

### C-3. 検証

```bash
grep -H numberOfSubdomains system/decomposeParDict system/*/decomposeParDict
# → 全ファイルが numberOfSubdomains 4 で一致していること
```

- [ ] global + 全領域分が同じ `numberOfSubdomains`
- [ ] 物理コア数を超えていない（4）

---

## 5. 完了ゲート（[6]へ）

```
[4b] 完了チェック
  Part A 底面パッチ
    □ boxToFace Z = 採取④実値 ±0.011mm（桁の検算済み: e-3 オーダー）
    □ topoSet -region + createPatch -region 実行
    □ cat boundary で <region>_bottom が nFaces>0 ★
  Part B changeDict
    □ 全パッチを実パッチ名で明示列挙（採取⑤）
    □ ".*" 併用なし / カップリングBC名正
    □ 熱抵抗は両側 + t/κ 検算（kappaLayers W/mK）
    □ 残骸パッチ zeroGradient化（採取⑥）
    □ 底面 fixedValue
  Part C decomposePar
    □ global + 全領域 numberOfSubdomains 一致
    □ 物理コア数以内
```

Part Aは実行済み（メッシュにパッチ追加済み）、Part B/Cは**書いた状態**で[6]へ渡す。[6]の実行直前に `changeDictionary -region` と `decomposePar -region` を走らせる。

---

## 6. 他形状への転用（差分ポイント）

| 変わる前提 | 4bで変わる箇所 |
|---|---|
| 流体領域が入る | 流体側のBC（U, p_rgh, k, ε, nut, alphat）も changeDict対象。界面の kappaMethod は流体側 `fluidThermo`／流入出BC追加 |
| 底面が複数 or 上面冷却 | Part Aを各冷却面で実施（採取④を各面で） |
| 界面熱抵抗が多数 | B-1の検算表を界面ごとに作り、両側ペアを漏れなく |
| 対流境界（固定温度でなく熱伝達係数） | 底面を fixedValue でなく `externalWallHeatFluxTemperature`（h指定）等に |
| コア数の違うPC | Part Cの numberOfSubdomains を物理コア数に合わせ、global+領域別を一括変更 |

**不変なもの**: 採取④⑤⑥の消費構造、changeDictの3鉄則、熱抵抗の `t/κ` 検算と面積換算、decomposeParの一致鉄則。

# 任务：把《无双·虎牢关》的画面升级到「实时照片级」

在**已有产物** `demos/index.html`（单文件割草游戏，2454 行 / 224 KB）上做**渲染层升级**。
玩法、关卡导演、HUD、输入、`__dbg` 契约保持可用；只改「看起来像什么」，不改「玩起来是什么」。

照片级 = **实时渲染约束下的最高保真**，不是离线渲染。
允许 stylized-realistic（风格化写实），**禁止**用照片贴图冒充 3D 质感。

---

## 0. 硬边界（违反即算未完成）

| # | 约束 | 判定方式 |
|---|---|---|
| B1 | 产物仍是**单文件** `demos/index.html`，只允许 three.js 从 CDN 加载 | 全文只有 1 个 `<script type="module">`，外部 URL 仅 `cdn.jsdelivr.net/npm/three@0.160.0` |
| B2 | **零外部资源**：不许加载外部模型 / 图片 / HDRI / 音频文件 | 不出现 `GLTFLoader` `RGBELoader` `TextureLoader` `AudioLoader`；`fetch(`/`XMLHttpRequest` 在非 three 内部不得出现 |
| B3 | 贴图必须**程序化生成**（canvas / DataTexture / 噪声函数），几何必须来自 Blender 脚本 base64 内嵌 | 贴图来源可枚举；`GEO_B64` 由 `scripts/blender/build_geometry.py` 产出 |
| B4 | 产物体积（未压缩）≤ **900 KB** | `wc -c demos/index.html` |
| B5 | 玩法数值、关卡时序、HUD DOM 结构、`__dbg` 方法名与返回字段**语义不变** | 现有 `scripts/verify.py` 必须仍能 18/18 通过（可新增断言，不可删旧断言） |
| B6 | 不新建 `CLAUDE.md` / `AGENTS.md`，不改任务目录之外的路径 | 目录树 diff |

---

## 1. 光影管线（P0，先做这条）

1. **HDR 链路**：场景渲染进 `HalfFloatType` 的 `WebGLRenderTarget`，后期在 HDR 里做 Bloom / 色调映射，最后一个 pass 才转 sRGB。
   - 注意：r160 的 `EffectComposer` **默认已用 HalfFloatType**，所以「是不是 HDR」不是重点；重点是**全链路无 8-bit 截断**：
     `composer.renderTarget1.texture.type === HalfFloatType`，中间任何 pass 不得改成 `UnsignedByteType`，
     Bloom 阈值（现在 0.82）必须落在 HDR 值域上，不得先 clamp 再 bloom。
   - 注意：r160 里 `renderer.toneMapping` **只在渲染到 canvas 时生效**（`currentRenderTarget === null` 才套用），
     所以 `EffectComposer` 链路下它等于死配置——现在的 ACES 其实是自写 `FinalShader` 在做。
     要求：**最终 pass 独占色调映射**，把 `renderer.toneMapping` 设为 `NoToneMapping` 以免误用，
     并把 ACES/AgX 的曲线与参数显式写在一个 `ShaderPass` 里。
   - `renderer.outputColorSpace = SRGBColorSpace`；所有 albedo/emissive 贴图 `colorSpace = SRGBColorSpace`，normal/roughness/ORM 必须 `NoColorSpace`。
   - 禁止「先 sRGB 编码再当线性采样」的双重转换（检查每张贴图的 colorSpace 是否与其用途匹配）。
2. **太阳 + 阴影**
   - 1 张 2048²（Retina 下 ≥ 2048²）shadow map，`PCFSoftShadowMap` 或 `VSM`；`shadow.bias` / `normalBias` 调到无 acne 且无 peter-panning。
   - 玩家周围 **tight frustum**：以玩家为中心、半径 ≤ 26 m 的正交投影，禁用 140 m 级大范围阴影导致分辨率浪费。
   - 单位必须投影（现在用胶囊代理）：**皮肤化角色本体投影**，代理仅作兜底。
   - 至少 **2 段级联**或等效方案，保证近处接触阴影清晰、远处不闪。
3. **IBL**：程序化 equirect（≥ 1024×512）经 `PMREMGenerator` 生成，必须包含
   太阳盘（与 DirectionalLight 同向同色温）、天空渐变、地面反弹色（干黄土偏暖褐）。
   所有 PBR 材质显式设置 `envMapIntensity`（金属 ≥ 1.0，织物 ≤ 0.5）。
4. **全局光照近似**（至少做 2 项）
   - SSAO（半分辨率，≤ 12 sample，带 bilateral blur）或顶点 AO 烘焙；
   - 地面/道具的**接触阴影**（贴地 blob 升级为按曲率/高度衰减）；
   - 一次性**光照探针/球谐**（可用 `LightProbe` + 程序化 SH 系数）或直接对静态道具烘焙顶点色 AO。
5. **大气与体积**
   - `FogExp2` + **高度雾**（地面 1.5 m 内更浓），远山要有明显大气透视（颜色趋近天空、对比度下降 ≥ 40%）。
   - **God rays / 光轴**：半分辨率屏幕空间径向模糊或 ray-march（步数 ≤ 24），强度随视角与遮挡变化；必须能在画质降级时整段关闭。
   - 天空：保留 ShaderMaterial 渐变 + 太阳盘，但加 **Mie 散射近似**（前向散射瓣 `pow(dot, 8)`）与地平线霾。
6. **色彩**：最终 pass 里做 ACES 或 AgX（选一）+ 曝光 + 对比 + 饱和 + 分离色调 + 暗角；
   必须给出**可复现的固定参数**（不许随机），并保留现有 `uWarm/uVig` 语义。
7. **后期 pass 总数 ≤ 5**（Bloom / SSAO / 体积光 / 色调 / 输出各算一个）。

---

## 2. 质感（P0/P1）

1. **至少 5 类 PBR 材质**，全部 `MeshStandardMaterial` / `MeshPhysicalMaterial`，参数可枚举：
   | 材质 | 关键参数 |
   |---|---|
   | 淬钢/铁甲 | metalness 0.90–1.0，roughness 0.15–0.35，带各向异性拉丝或 `anisotropy` |
   | 皮革/织物（披风、战袍） | `sheen` / `sheenColor` / `sheenRoughness`，roughness 0.75–0.95 |
   | 干裂黄土 | albedo + normal + roughness 三张，法线由高度图 `Sobel` 生成，strength 可调 |
   | 木/漆器（关楼、箭楼、辎重箱） | 木纹走向沿长轴，roughness 0.55–0.8 + 清漆层 |
   | 血肉/皮肤 | `MeshPhysicalMaterial` 近似 SSS（`transmission` 或 `thickness`+`sheen` 低强度），禁止塑料高光 |
2. **贴图通道**：至少 albedo / normal / roughness 三张（可 ORM 打包）；地面 ≥ 2048²，其它 ≥ 512²；
   全部 `generateMipmaps` + `anisotropy ≥ 4` + `RepeatWrapping`。
3. **去平铺**：地面用 **双尺度 UV**（macro 2 档 + detail 1 档）或 macro variation 遮罩，禁止肉眼可见的重复格。
4. **磨损与叙事**：边缘倒角高光（curvature 或顶点 AO）、随机泥点/血迹沉积（程序化，密度随单位状态变化）、
   每实例 per-instance 色相/明度扰动 **±5%**、每实例 `roughness` 扰动 ±0.08。
5. **地面**：必须有踩踏痕、车辙、血迹、碎石的分布逻辑（按战场中心密、边缘疏），而不是均匀噪点。

---

## 3. 人物骨模（P1）

1. **Blender 管线扩展**（`scripts/blender/build_geometry.py`）
   - 产出 **5 个 skinned 角色**：玩家赵云（白甲金边红缨白袍长枪）+ 刀兵 / 枪兵 / 弓兵 / 敌将（华雄、吕布共用骨架，换网格与配色）。
   - 每个角色：**单网格**（所有部件合并，1 个材质，靠顶点色 + 贴图区分），**≤ 3500 三角面**，**≤ 24 根骨骼**，**≤ 4 根权重/顶点**，权重归一化。
   - 骨架层级必须是可用的简化人形（root → hips → spine → chest → neck/head → shoulder/arm ×2 → leg ×2 + 武器挂点），关节朝向一致，便于程序化动作复用。
2. **内嵌格式**（在现有 `[nv:u32][ni:u32][pos][col][idx]` 上向后扩展，保持旧字段可读）
   ```text
   [nv:u32][ni:u32][pos:f32×nv*3][col:u8×nv*4][idx:u16×ni*3]
   + [nJoint:u8][parent:u8×nJoint]
   + [joints:u8×nv*4][weights:u8×nv*4]
   + [bindMat:f32×nJoint*16]
   + clips: { name, dur, tracks:[{joint, prop, keys:[u16 t, f32 v]}] }
   ```
   - 用 `Uint8Array` + `DataView` 解码，**不许**在运行时 `JSON.parse` 大块文本以外的方式退化。
3. **动画 clip（至少 10 个）**：`idle` / `walk` / `run` / `atk1` / `atk2` / `atk3` / `heavy` / `hit` / `die` / `musou`；
   每 clip ≤ 40 帧，关键帧用 `u16` 时间 + 量化数值；循环 clip 首尾必须对齐（误差 ≤ 1 帧）。
4. **运行时**：`THREE.SkinnedMesh` + `Skeleton` + `AnimationMixer`；切换用 `crossFadeTo`（0.08–0.15 s）；
   **攻击命中帧必须由 clip 的 time 驱动**，不再用 `atkP > 0.40` 这种硬编码阈值（可保留阈值作为兜底）。
5. **同屏 60 人的成本约束（关键）**
   - 单角色单网格 = 60 单位 ≈ 60 draw call + 60 阴影 draw；**超过 260 draw call 就必须做优化**。
   - **动画 LOD 必须实现**（按到玩家距离）：
     | 距离 | 更新率 | 说明 |
     |---|---|---|
     | ≤ 18 m | 60 Hz | 全量 mixer 更新 |
     | 18–35 m | 20 Hz | 隔帧更新 + 姿态插值 |
     | 35–60 m | 10 Hz | 只更新骨骼矩阵 |
     | > 60 m | 静态 | 冻结当前姿态 + 顶点级摆动（可选） |
   - 允许且鼓励：把骨骼矩阵上传到 `DataTexture` + `InstancedMesh` 做 GPU skinning（加分项，非必需）。
   - **禁止**给每个单位各建一份全量 `AnimationMixer` 且每帧全量 `update()`。
6. **保留**现有的低模胶囊阴影代理作为兜底；皮肤化本体投影打开后，代理可降级为只写 `depth` 的轻量版本。

---

## 4. 性能（P1，**不可让步**）

验收脚本 `__dbg.spawn(60)` 后，本机 Chrome / Apple M1 / 1440×810：

| 指标 | 下限 | 上限 |
|---|---|---|
| 帧率 | ≥ **58 fps**（均值） | — |
| draw call | — | ≤ **260** |
| 三角面 | — | ≤ **1.5 M** |
| 亮度 mean | 0.30 – 0.80 | — |
| 过曝 clipped | — | ≤ 2.0 % |
| 死黑 nearBlack | — | ≤ 12 % |

自适应画质规则：
- `quality ∈ [0.55, 1.0]`，只允许降级 **渲染比例 / 阴影分辨率 / SSAO 采样 / 体积光步数 / 粒子数**；
- **不许**把动画 LOD 降到 10 Hz 以下（动作会变鬼畜）；
- 降级要**可观测**：`__dbg.info()` 增加 `shadowRes` / `ssao` / `volumetrics` / `animLod` 字段（新增字段，不删旧字段）。

---

## 5. 验收（必须全绿）

保留 `scripts/verify.py` 现有 18 条断言全部通过，**并新增**至少 12 条（写进 `scripts/verify_photo.py`，或扩展 verify.py 并加 `--photo`）：

> **验收脚本由你自己写，但评分权不在你手里。** 以下 14 条是**需求规格**，不是建议：
> 1. 每条断言的阈值必须**逐字取本文件 §4 表格与下表 P1–P14 的数值**，不得自行放宽（例如把 58 改 45、把 260 改 400）。
> 2. 每条断言必须打印**实测值**，格式 `[PASS|FAIL] 名称 — 实测值 / 期望区间`；只打印 PASS 不打印数值的断言**视为无效**。
> 3. 不许跳过、注释或 `try/except` 掉任何一条；失败就让它失败，然后回去改画面。
> 4. 必须额外打印一份**资产清单**（材质种类与参数、贴图尺寸、skeleton 骨骼数、clip 名、skinned mesh 数量），供人工核对 P4/P5/P6/P8。
> 5. 不许修改 `scripts/verify.py` 的既有 18 条断言；`--photo` 模式下必须**先跑完旧 18 条再跑新 14 条**。

| # | 断言 |
|---|---|
| P1 | 全链路无 8-bit 截断：`composer.renderTarget1.texture.type === HalfFloatType`，且所有 pass 的 RT 均为 HalfFloat（读 `__dbg.info().hdr === true`） |
| P2 | `renderer.toneMapping === NoToneMapping`（色调映射由最终 pass 独占），`outputColorSpace === SRGBColorSpace` |
| P3 | 阴影贴图 ≥ 2048²（`sun.shadow.mapSize` 可读） |
| P4 | 场景内 PBR 材质种类 ≥ 5，且金属/织物/地面参数在区间内 |
| P5 | 地面贴图 ≥ 2048²，且 normal/roughness 通道存在 |
| P6 | 角色为 `SkinnedMesh`，`skeleton.bones.length ≤ 24` |
| P7 | 角色网格为单 mesh（`scene` 中 skinned mesh 数量 ≤ 单位数 + 4） |
| P8 | 动画 clip 数 ≥ 10，且 10 个 clip 名齐全 |
| P9 | 顶点权重 ≤ 4，且权重和归一化误差 ≤ 1e-3 |
| P10 | 60 人同屏帧率 ≥ 58，draw call ≤ 260，三角面 ≤ 1.5 M |
| P11 | 亮度 / 过曝 / 死黑三项在 §4 区间内 |
| P12 | 远/近 LOD 切换有效（20 单位混排时 `animLod` 字段出现 ≥ 2 个不同档位） |
| P13 | 截图证据 5 张：标题 / 战斗 / 无双 / 敌将 / 结算，且画面无明显平铺重复 |
| P14 | 全程零 JS 运行时错误、零 console 报错 |

---

## 6. 反模式（明确禁止）

- ✗ 用外部 HDRI / 贴图 / glTF；用 base64 塞照片贴图充数（体积与「程序化」双违规）。
- ✗ 为画质把同屏降到 30 人以下，或让帧率掉到 45 以下还宣称完成。
- ✗ SSAO / 体积光做成全屏高分辨率（必须半分辨率 + 可关）。
- ✗ 改 `__dbg.st()` / `info()` / `lum()` 的**已有字段名与语义**（只能新增）。
- ✗ 改玩法数值（`TYPES` 表的 hp/spd/dmg/range/wind/strike/rec）、关卡时序、HUD DOM 结构。
- ✗ 为省性能把角色合并成「一个姿态贴图」而失去骨骼动画（本任务的核心就是骨模）。
- ✗ 靠"看起来对"收工：每个视觉结论要有截图，每个逻辑结论要有 `__dbg` 快照。
- ✗ 以为 `renderer.toneMapping = ACESFilmicToneMapping` 生效了就完事（r160 里它只在渲染到 canvas 时生效）。
- ✗ 把 `EffectComposer` 的 RT 换成 8-bit「省性能」（会让所有 HDR 光照在 tone mapping 前被截断，暗部断层）。

---

## 7. 汇报格式（结尾 3–8 行）

```
做了什么（一句话）
文件路径：demos/index.html（+ scripts/blender/build_geometry.py 的改动）
已知问题（≤ 3 条，具体到现象）
实测：fps / draw call / tris / 亮度 mean·clipped·nearBlack / GPU 字符串
披露：是否为软渲染（SwiftShader 则写"未在真 GPU 上验证"）；音频未经人耳试听（若改了音频）
```

---

## 8. 执行建议（模型自用，不是交付物）

1. **先做 P0 光影 + 色彩管线**，用现有几何验证（此时角色仍是部件层级），截图对比后再上骨模。
2. 再替换角色几何为 skinned 单网格，先只接 `idle/walk/run/atk1-3`，帧率与 draw call 达标后再补 clip。
3. 最后做 SSAO / 体积光 / 磨损细节，边做边看 `__dbg.info()`。
4. 每完成一个阶段跑一次 `python3 scripts/verify.py` + 新增断言，**不要**攒到最后一起调。

## 9. 预算

```bash
scripts/run.sh prompts/02-photo.md 1h 60     # 缓存 1h，预算 60 美元
python3 scripts/verify.py && python3 scripts/verify_photo.py
```
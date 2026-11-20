# PC 全卡能力覆盖清单

> 由 `python dev/card_coverage.py --write` 生成；`--check` 只读核对。不要手改。

卡库 **1646 条**，**1588 个名称**，**48 组重名**。每个 cardId 单列，详见 [JSON](card_coverage.json)。

既有规则放行 **529 个指令规则名**（含 27 个天气效果版本），本轮新增放行 **0**。

## 如何阅读

- `eligible` 仅指默认规则可选；当前费用、橙色、身份、合法目标、前台与动作后验仍须通过。
- `conditional` 的天气纯名称不可出，必须解析效果版本；不要把天气家族与版本重复当成全卡数量。
- `disabled` 表示现行规则禁用；`unreviewed` 表示规则尚未核定，不等同仅缺拖拽实现。
- 基础费用/攻防/阵营来自 `json`，不是当前战场状态；不得用基础属性假算斩杀或交换。
- `strategy_evaluation`、`per_card_live_evidence` 均为 `not_indexed`：尚无逐卡可追溯索引，不表示历史实机从未用过。既有场次证据仍见 PC 报告，不能用规则放行替代。
- 单位通用部署路径也不能证明其所有部署效果、选目标、关键词和特殊机制已适配。

## 当前执行路径

| 路径 | 记录数 |
|---|---:|
| blacklist | 82 |
| choice | 27 |
| counter_unimplemented | 50 |
| direct | 277 |
| follow | 2 |
| hand_choice | 10 |
| ignored | 1 |
| target | 180 |
| three | 19 |
| unit_deploy | 959 |
| unmarked_choice | 16 |
| unreviewed | 14 |
| weather_variant_required | 9 |

## 本轮明确的待办

- 征服、美国陆军航空队：中英文均未要求玩家指定目标，可复用 direct 手势；但空抽、手牌容量和收益条件未验证，维持不放行。
- 暂避锋芒/装甲楔形阵：需当前单位身份、阵营、类型及费用限制，不用基础卡库字段猜当前合法性。
- 二步/手牌选择/限定目标/提前结束回合指令继续逐张审查；不批量改为 direct。
- 现行固定优先级没有完整攻防交换评估；当前属性、关键词和持续效果采集是前置缺口。

## 逐卡索引

| cardId | 卡名 | 类型 | 基础费 | 规则 | 路径 | 说明 |
|---|---|---|---:|---|---|---|
| 1005th_rifles | 步兵第 1005 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 101_infantry_regiment | 第 101 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 101st_airborne | 第 101 空降师 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 101st_bezhitsa | 别日察第 101 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 102_grenadier | 第 102 掷弹兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 102_grenadier_vet | 第 102 掷弹兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 102nd_rifles | 步兵第 102 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 102nd_rifles_vet | 步兵第 102 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 103rd_cavalry_recon | 第 103 骑兵侦察小队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 104_panzergrenadier | 第 104 装甲掷弹兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 104th_infantry_regiment | 第 104 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 106th_infantry_regiment | 步兵第百六联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 106th_quartermasters | 第 106 军需连 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1081st_smolensk | 斯摩棱斯克第 1081 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 108_panzergrenadier | 第 108 装甲掷弹兵团 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1097_volksgrenadier | 第 1097 国民掷弹兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 109th_combat_engineers | 第 109 战斗工兵营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 10_5_cm_lefh | 105 毫米轻型榴弹炮 | artillery | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 10th_engineers_battalion | 第 10 工兵营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 10th_guards_regiment | 近卫步兵第 10 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 10th_para_battalion | 第 10 伞兵营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 10th_recon | 搜索第十联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 110_panzergrenadier | 第 110 装甲掷弹兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 110e_rgiment_motoris | 第 110 摩托化步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 111th_indian_brigade | 第 111 印度旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 112th_infantry_regiment | 第 112 步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 113_schtzen | 第 113 步枪兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 114th_infantry_regiment | 步兵第百十四联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 115th_separate_btn | 独立第 115 营 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 116th_infantry_regiment | 第 116 步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 118th_mixed_regiment | 步兵第百十八联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 119_grenadier | 第 119 掷弹兵团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 119_grenadier_vet | 第 119 掷弹兵团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 11th_infantry_regiment | 第 11 流浪者步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 120mm_m1_gun | 120 毫米高射炮 | artillery | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 121st_infantry_regiment | 第 121 步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 122nd_korsun | 科尔孙第 122 团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 123s | 第 123 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 125th_la_spezia | 拉斯佩齐亚第 125 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 125th_rifle_regiment | 步兵第 125 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1271st_rifles | 步兵第 1271 团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 128th_rifles | 步兵第 128 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 12th_guards_mechanised | 近卫机械化第 12 旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 12th_guards_mechanised_vet | 近卫机械化第 12 旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 12th_infantry_regiment | 第 12 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 12th_uan | 第 12 乌兰骑兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 132nd_omsk | 鄂木斯克第 132 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 133rd_ironman | 第 133 铁人步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1357th_rifles | 步兵第 1357 团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 136_gebirgsjger | 第 136 山地猎兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 139_gebirgsjger | 第 139 山地猎兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 13_gebirgsjger | 第 13 山地猎兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 13e_dragons | 第 13 龙骑兵团 | infantry | 0 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 13th_engineers_battalion | 第 13 工兵营 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 13th_rifle_regiment | 步兵第 13 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 141_gebirgsjger | 第 141 山地猎兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 142nd_infantry_regiment | 第 142 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 144th_infantry_regiment | 步兵第百四十四联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 146th_infantry_regiment | 步兵第 146 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 14_panzergrenadier | 第 14 装甲掷弹兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 14_panzergrenadier_vet | 第 14 装甲掷弹兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 14th_brigade_nz | 新西兰第 14 旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 14th_guard_rifles | 近卫步兵第 14 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 14th_guard_rifles_vet | 近卫步兵第 14 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 151st_infantry_regiment | 步兵第百五十一联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 152e_rgiment | 第 152 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 152mm_howitzer_gun | 152 毫米榴弹炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 155_c_modle_1917 | 155 毫米榴弹炮 1917 | artillery | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 155mm_1918_model | 155 毫米榴弹炮 1918 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 158_nachschub | 第 158 补给营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 158th_bushmasters | 第 158 蝮蛇步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 15_aufklrung | 第 15 侦察营 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 15_cm_autokanone | 150 毫米榴弹炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 15th_cavalry_regiment | 骑兵第十五联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 15th_engineers | 第 15 工兵营 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 15th_motor_rifles | 摩托化步兵第 15 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 15th_recce | 第 15 侦察团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 15th_wolves_regiment | 第 15 狼步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 162nd_regiment | 第 162 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 164th_infantry_regiment | 第 164 步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 169_grenadiers | 第 169 掷弹兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 16th_infantry_brigade | 第 16 步兵旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 16th_infantry_brigade_vet | 第 16 步兵旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 16th_rifles | 步兵第 16 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 16th_tarnow_regiment | 塔尔努夫第 16 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 171_infantry_regiment | 第 171 步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 173rd_guard_rifles | 近卫步兵第 173 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 174th_independent | 独立步兵第百七十四大队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 175th_infantry_regiment | 第 175 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 175th_motorized | 摩托化步兵第 175 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 178th_guard_rifles | 近卫步兵第 178 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 179th_tomahawks | 第 179 战斧步兵团 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 179th_tomahawks_vet | 第 179 战斧步兵团 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 17_pounder | 17 磅炮 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 17th_infantry_brigade | 第 17 步兵旅 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 17th_infantry_regiment | 第 17 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 17th_rifle_regiment | 步兵第 17 团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 182_landwehr | 第 182 国土防卫团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 182_landwehr_vet | 第 182 国土防卫团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 185th_brigade | 第 185 步兵旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 185th_folgore | 第 185 雷电伞兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 186th_folgore | 第 186 雷电伞兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 186th_recon_company | 侦察第 186 连 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 18_infantry_regiment | 第 18 步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 18e_rgiment | 第 18 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 18th_bersaglieri | 第 18 神射手团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 190th_guard_rifles | 近卫步兵第 190 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 190th_guard_rifles_vet | 近卫步兵第 190 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 199th_rifle_regiment | 步兵第 199 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1_infantry_regiment | 第 1 步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1er_bcp | 第 1 猎兵营 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1er_hussards | 第 1 骠骑兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1er_rgiment_tranger | 外籍第 1 步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1re_bfl | 第 1 旅 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_airborne | 第 1 伞兵旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_airlanding_brigade | 第 1 空降旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_cavalry_troop | 第 1 骑兵侦察小队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_defense_battalion | 第 1 防卫营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_florida | 第 1 佛罗里达州步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_grenadier_regiment | 第 1 掷弹兵团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_gurkha_rifles | 第 1 廓尔喀团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_infantry_regiment | 永先者团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_london_brigade | 第 1 伦敦旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_marines | 第 1 陆战团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_rifles | 近卫步兵第 1 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_san_marco | 圣马可第 1 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_signal_regiment | 电信第一联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_taipei_regiment | 海联队 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_texas_infantry | 德州第 1 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 1st_yokosuka | 横镇第一特别陆战队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 204th_guards | 近卫步兵第 204 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 20_panzergrenadier | 第 20 装甲掷弹兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 20th_infantry_regiment | 塞班混成守备队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 211th_tokyo | 步兵第二百一十一联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 214th_amur | 阿穆尔第 214 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 216th_guards | 近卫步兵第 216 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 216th_guards_vet | 近卫步兵第 216 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 220th_rifles | 步兵第 220 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 222nd_guard_rifles | 近卫步兵第 222 团 | infantry | 9 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 22_infantry_regiment | 第 22 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 22nd_guards_brigade | 第 22 卫队旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 22nd_guards_brigade_vet | 第 22 卫队旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 22nd_marines | 第 22 陆战团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 22nd_marines_vet | 第 22 陆战团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 22nd_pioneers | 第 2/2 先锋营 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 238th_regiment | 步兵第二百三十八联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 24th_cavalry_regiment | 骑兵第二十四联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 24th_uan | 第 24 乌兰骑兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 252nd_rifles | 步兵第 252 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 252nd_rifles_vet | 步兵第 252 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 25_marines | 第 5 陆战团 2 营 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 25_panzergrenadier | 第 25 装甲掷弹兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 25_pounder | 25 磅炮 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 25_pounder_mk_i | 25 磅炮 Mk I | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 25th_infantry_regiment | 步兵第 25 团 | infantry | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 266th_guard_rifles | 近卫步兵第 266 团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 266th_guard_rifles_vet | 近卫步兵第 266 团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 269th_rifles | 步兵第 269 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 269th_rifles_vet | 步兵第 269 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 26_engineer_regiment | 第 26 工兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 26th_infantry_regiment | 第 26 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 272nd_guards | 近卫步兵第 272 团 | infantry | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 27_fsiliers | 第 27 燧发枪兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 27e_dia | 阿尔卑斯第 27 师 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 27th_mg_battalion | 第 27 机枪营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 289th_gatchina | 加特契纳第 289 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 28_jger_regiment | 第 28 猎兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 28cm_coastal_howitzer | 280 毫米榴弹炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 28th_infantry_regiment | 第 28 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2_marine_division | 第 2 海军步兵师 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2_pounder | 2 磅炮 | artillery | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2e_brigade | 第 2 旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2e_rima | 第 2 陆战团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2e_rmt | 乍得行进团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2e_zouaves | 第 2 佐阿夫团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_alpini_regiment | 第 2 山地团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_california | 加州第 2 步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_infantry_regiment | 步兵第 2 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_marines_battalion | 海军陆战队第 2 营 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_michigan | 第 2 密歇根州步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_para_c | 第 2 伞兵营 C 连 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_parachute | 第 2 伞兵旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_raiding_brigade | 第二挺进团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_rifles | 摩托化步兵第 2 师 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 2nd_west_africa | 第 2 西非旅 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 304_panzergrenadier | 第 304 装甲掷弹兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 306th_regiment | 第 306 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 30_infantry_regiment | 第 30 步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 30th_regiment | 旧金山属团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 312th_novgorod | 诺夫哥罗德第 312 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 31e_algriens | 阿尔及利亚第 31 散兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 321st_rifle_regiment | 步兵第 321 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 327th_pathfinders | 第 327 探路者步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 327th_pathfinders_vet | 第 327 探路者步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 329th_engineer_battalion | 工兵第 329 营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 32nd_infantry_regiment | 第 32 步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 332nd_engineer_regiment | 第 332 工兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 334th_mountain_rifles | 山地步兵第 334 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 336th_guards_naval | 近卫海军步兵第 336 旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 33_panzergrenadier | 第 33 装甲掷弹兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 33rd_livorno_regiment | 利沃诺第 33 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 33rd_recon | 搜索第三十三联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 342_fsiliers | 第 342 燧发枪兵营 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 34th_guards | 近卫步兵第 34 团 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 34th_infantry_regiment | 橘联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 35_grenadier | 第 35 掷弹兵团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 35_grenadier_vet | 第 35 掷弹兵团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 35th_infantry_regiment | 第 35 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 35th_mountain_rifles | 山地步兵第 35 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 35th_rifle_regiment | 步兵第 35 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 361_afrika_regiment | 第 361 非洲兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 36_kradschtzen | 第 36 摩托化步兵营 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 36th_cavalry | 骑兵第 36 师 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 37_mm_antiaircraft_gun | 37 毫米高射炮 | artillery | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 37mm_bofors_gun | 博福斯 37 毫米炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 37mm_m1_aa_gun | 37 毫米 M1 高射炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 388th_independent | 独立步兵第三百八十八大队 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 38th_guard_rifles | 近卫步兵第 38 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 38th_independent | 独立混成第三十八旅团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 392nd_rifles | 步兵第 392 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 392nd_rifles_vet | 步兵第 392 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 394th_infantry_regiment | 第 394 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 39_panzergrenadier | 第 39 装甲掷弹兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 39th_bologna_regiment | 博洛尼亚第 39 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 39th_rifle_regiment | 步兵第 39 团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3_7_antiair_gun | 3.7 英寸高射炮 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3_7_inch_mountain_howitzer | 3.7 英寸山地榴弹炮 | artillery | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3_7cm_flak_37 | 自行高炮 37 型 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3_fallschirmjger | 第 3 空降猎兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3_panzergrenadier | 第 3 装甲掷弹兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3inch_m5 | M5 3 英寸反坦克炮 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_alpini_regiment | 第 3 山地团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_canadian_division | 第 3 加拿大师 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_carpathian | 喀尔巴阡第 3 步兵营 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_guards_regiment | 近卫步兵第 3 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_kure_snlf | 吴镇第三特别陆战队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_maizuru_snlf | 舞镇第三特别陆战队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_marine_regiment | 第 3 陆战团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_mixed_regiment | 混成第三联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_morskoi_pekhoty | 海军步兵第 3 旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 3rd_yokosuka | 横镇第三特别陆战队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 40_panzergrenadier | 第 40 装甲掷弹兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 40_royal_marine | 第 40 突击队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 40th_cavalry_regiment | 骑兵第四十联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 414th_rifles | 步兵第 414 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 41st_bicycle_regiment | 马来银轮部队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 41st_infantry_regiment | 第 41 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 42nd_rifles | 步兵第 42 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 432_infantry_regiment | 第 432 步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 43_infantry_regiment | 第 43 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 43e_rgiment_motoris | 第 43 摩托化步兵团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 442nd_infantry_regiment | 第 442 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 44th_silesia | 西里西亚第 44 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 456th_rifle_regiment | 步兵第 456 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 45_mm_antitank_gun | 45 毫米反坦克炮 | artillery | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 461st_rifles | 步兵第 461 团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 463rd_battalion | 第 463 空降炮兵营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 46th_indian_brigade | 第 46 印度旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 47th_infantry_regiment | 第 47 步兵团 | infantry | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 47th_infantry_regiment_vet | 第 47 步兵团 | infantry | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 48e_rgiment_dinfanterie | 第 48 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 48th_armored_infantry | 第 48 装甲步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 49th_infantry_regiment | 第 49 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 49th_karachev | 卡拉切夫第 49 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4_fallschirmjger | 第 4 空降猎兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4_pioneer_battalion | 第 4 先锋营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4e_brigade | 第 4 旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4th_alabama | 第 4 阿拉巴马州步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4th_alpini_regiment | 第 4 山地团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4th_brigade_nz | 新西兰第 4 旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4th_guards_rifles | 近卫步兵第 4 团 | infantry | 9 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4th_kuban_cossacks | 库班哥萨克第 4 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4th_marines | 第 4 陆战团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 4tp | 4TP | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 503rd_motors | 摩托化步兵第 503 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 506th_airborne | 第 506 空降步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 507th_pir | 第 507 空降步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 50_infantry_regiment | 第 50 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 50_infantry_regiment_vet | 第 50 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 511th_airborne | 第 511 空降步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 511th_regiment | 步兵第 511 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 511th_regiment_vet | 步兵第 511 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 51e_rgiment | 第 51 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 51st_recon | 搜索第五十一联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 51st_rifle_brigade | 步兵第 51 旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 52k | 52-K | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 54th_infantry_regiment | 步兵第五十四联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 554th_rifle_regiment | 步兵第 554 团 | infantry | 0 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 55th_rifles | 步兵第 55 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 56_jger_regiment | 第 56 猎兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 56th_recon | 搜索第五十六联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 573rd_rifles | 步兵第 573 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 57th_rifles | 步兵第 57 旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 58th_infantry_regiment | 步兵第五十八联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 593rd_jasco | 第 593 联合通信连 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 59_panzergrenadier | 第 59 装甲掷弹兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5_panzergrenadier | 第 5 装甲掷弹兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5e_chasseurs | 第 5 猎兵营 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5e_cuirassiers | 第 5 胸甲骑兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_bersaglieri | 第 5 神射手团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_brigade | 第 5 步兵旅 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_infantry_regiment | 第 5 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_legions_regiment | 第 5 军团步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_medical_battalion | 第 5 医疗营 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_parachute_brigade | 第 5 伞兵旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_rangers | 第 5 游骑兵营 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_regiment | 步兵第五联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_sasebo_snlf | 佐镇第五特别陆战队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 5th_wilno_brigade | 维尔纽斯第 5 步兵旅 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 60th_cavalry_regiment | 骑兵第 60 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 60th_infantry_regiment | 第 60 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 61st_infantry_regiment | 步兵第六十一联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 61st_kirkenes | 希尔克内斯第 61 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 62_infantry_regiment | 第 62 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 62nd_armored_infantry | 第 62 装甲步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 641st_rifles | 步兵第 641 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 641st_rifles_vet | 步兵第 641 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 64_panzergrenadier | 第 64 装甲掷弹兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 64_panzergrenadier_vet | 第 64 装甲掷弹兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 654th_rifles | 步兵第 654 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 66th_independent | 独立第六十六步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 676th_regiment | 步兵第 676 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 67th_baranovichi | 巴拉诺维奇第 67 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6_pounder | 6 磅炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_airborne | 近卫空降第 6 团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_airlanding_brigade | 第 6 空降旅 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_alpini_regiment | 第 6 山地团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_brigade_nz | 新西兰第 6 旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_brigade_nz_vet | 新西兰第 6 旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_infantry_brigade | 第 6 步兵旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_infantry_regiment | 步兵第六联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_marine_regiment | 第 6 陆战团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_motor_rifles | 摩托化步兵第 6 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 6th_naval_brigade | 海军步兵第 6 旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7075_aluminium | 7075 铝 | order | 0 | eligible | direct | B#1(未特别指定) |
| 70th_brigade | 第 70 步兵旅 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 71st_zhytomyr | 日托米尔第 71 团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 738_jger_regiment | 第 738 猎兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 73e_rgiment_dinfanterie | 第 73 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 73rd_infantry_regiment | 步兵第七十三联队 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 740th_rifle_regiment | 步兵第 740 团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 74_panzergrenadier | 第 74 装甲掷弹兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 74th_silesian_regiment | 西里西亚第 74 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 756th_regiment | 步兵第 756 团 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 75mm_field_artillery | 九零式野战炮 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 75mm_mountain_gun | 四一式山炮 | artillery | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 75mm_pack_howitzer | 75 毫米驮载榴弹炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 75th_rangers | 第 75 游骑兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 75th_rifle_regiment | 步兵第 75 团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 76_mm_howitzer_1939 | 76 毫米榴弹炮 1939 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 76th_napoli | 那不勒斯第 76 团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 77th_guards | 近卫步兵第 77 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 77th_regiment | 步兵第七十七联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 78th_steel_regiment | 第 78 钢铁步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 78th_yongsan | 步兵第七十八联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 79th_infantry_regiment | 步兵第七十九联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7_schtzen | 第 7 步枪兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7_schtzen_vet | 第 7 步枪兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7th_alpini_regiment | 第 7 山地团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7th_brigade | 第 7 旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7th_brigade_vet | 第 7 旅 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7th_recon | 搜索第七联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7th_regiment | 第 7 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7th_scottish_borderers | 苏格兰边民团第 7 营 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 7tp | 7TP | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 80th_pasubio | 帕苏比奥第 80 团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 81_infantry_regiment | 第 81 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 83rd_naval_brigade | 海军步兵第 83 旅 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 845th_rifles | 步兵第 845 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 84th_infantry_regiment | 步兵第 84 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 85_pioneer_company | 第 85 先锋连 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 85mm_d44_field_gun | 85 毫米野战炮 | artillery | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 866th_rifles | 步兵第 866 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 87_grenadier | 第 87 掷弹兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 88_mm_flak | 88 毫米高射炮 | artillery | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 89th_infantry_regiment | 步兵第 89 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 8_fallschirmjger | 第 8 空降猎兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 8e_marocains | 摩洛哥第 8 散兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 8th_cavalry_regiment | 第 8 骑兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 8th_marines | 第 8 陆战团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 909th_roslavl | 罗斯拉夫尔第 909 团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 91st_astrakhan | 阿斯特拉罕第 91 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 92_infantry_regiment | 第 92 步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 92nd_naval_brigade | 海军步兵第 92 旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 93rd_messina | 墨西拿第 93 团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 957_volksgrenadier | 第 957 国民掷弹兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 95th_rifle_regiment | 步兵第 95 团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 96_infantry_regiment | 第 96 步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 97th_rifles | 步兵第 97 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 980_volksgrenadier | 第 980 国民掷弹兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 989_infantry_regiment | 第 989 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 99th_infantry_battalion | 第 99 步兵营 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 99th_kholm | 霍尔姆第 99 团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 9_2_coastal_gun | 9.2 英寸岸防炮 | artillery | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 9th_bersaglieri | 第 9 神射手团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| 9th_guards_regiment | 近卫步兵第九联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a20_havoc | A-20 浩劫 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a20b | A-20B | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a24_banshee | A-24 女妖 | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a26_invader | A-26 入侵者 | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a34_comet | A34 彗星 | tank | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a36_apache | A-36 阿帕齐 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a5m4_claude | A5M4 九六舰战 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a6m221_zero | A6M2 零战二一型 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a6m2_zero | A6M2 零战 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a6m3_zeke | A6M3 零战三二型 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| a_bridge_too_far | 遥远的桥 | countermeasure | 5 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| a_few_good_men | 好人寥寥 | order | 2 | eligible | three | 需要目标#97 |
| aa_barrage | 防空弹幕 | order | 1 | disabled | blacklist | 需要目标#77 |
| ace_of_spades | 黑桃 A 师 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ace_of_spades_vet | 黑桃 A 师 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| act_on_the_intel | 见机行事 | order | 6 | eligible | target | 需要目标#204 |
| active_sonar | 主动声呐 | order | 0 | eligible | direct | A#1 |
| admiral_yamamoto | 山本五十六 | order | 1 | eligible | direct | A#20 |
| advanced_imperial_rd | 高级帝国研发 | order | 9 | eligible | choice | 抉择#39 白名单:两个选项 / 选左边 |
| advanced_reich_rd | 高级德意志帝国研发 | order | 9 | eligible | choice | 抉择#40 白名单:两个选项 / 选左边 |
| advanced_royal_research | 高级皇家研发 | order | 9 | disabled | unmarked_choice | 抉择#41:不在白名单里 |
| advanced_soviet_research | 高级苏联研发 | order | 9 | eligible | choice | 抉择#43 白名单:两个选项 / 选右边 |
| advanced_us_research | 高级美国研发 | order | 9 | eligible | choice | 抉择#42 白名单:两个选项 / 选右边 |
| aerial_reconnaissance | 空中侦察 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| aerosani | 气动雪橇 | order | 0 | eligible | target | 需要目标#11 |
| afrika_korps | 非洲军团 | order | 2 | eligible | three | 需要目标#139 |
| against_the_odds | 迎难而上 | countermeasure | 0 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| agency_africa | 非洲情报局 | order | 2 | eligible | direct | B#93(未特别指定) |
| aichi_d3a1 | D3A1 九九舰爆 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| aichi_d3a2 | D3A2 九九舰爆 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| aid_to_the_front | 如虎添翼 | order | 1 | disabled | blacklist | 需要目标#38 |
| air_blitz | 空中闪击 | order | 3 | eligible | target | 需要目标#163 |
| air_corps_ferrying | 航空兵团运输 | order | 1 | eligible | target | 需要目标#68 |
| air_cover | 空中掩护 | order | 3 | eligible | direct | A#82 |
| air_defense | 防空 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| air_escort | 空中护航 | order | 2 | eligible | direct | A#56 |
| air_land_sea | 海陆空 | order | 1 | eligible | three | B#27 用户指定 |
| air_power | 空军力量 | order | 3 | disabled | unmarked_choice | 抉择#24:不在白名单里 |
| air_strips | 跑道 | order | 1 | eligible | direct | B#38(未特别指定) |
| air_superiority | 空中优势 | order | 1 | eligible | target | 需要目标#63 |
| air_support | 空中支援 | order | 3 | disabled | blacklist | 需要目标#162 |
| airdrop | 空降 | order | 3 | eligible | target | B#118 用户指定 |
| airstrike | 空袭 | countermeasure | 3 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| akita_regiment | 秋田联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| albacore_mk_i | 青花鱼 Mk I | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| allied_research_effort | 盟军研发成果 | order | 1 | eligible | choice | 抉择#8 白名单:两个选项 / 选左边 |
| alpenfestung | 阿尔卑斯要塞 | order | 7 | eligible | direct | A#147 |
| america_at_war | 战时美利坚 | order | 3 | eligible | direct | B#111(未特别指定) |
| amphibious_assault | 两栖进攻 | order | 3 | disabled | blacklist | 需要目标#144 |
| ancestral_call | 卫国英烈 | order | 6 | eligible | direct | A#138 |
| ancient_empire | 古老帝国 | order | 2 | eligible | direct | B#54(未特别指定) |
| anders_army | 安德斯军团 | order | 1 | eligible | direct | A#19 |
| annihilation | 歼灭 | order | 7 | eligible | target | 需要目标#205 |
| arado_ar_196 | Ar 196 | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| arctic_convoy | 北极护航队 | order | 4 | eligible | direct | A#98 |
| area_bombardment | 区域轰炸 | order | 6 | eligible | direct | B#177(未特别指定) |
| argyllshire_highlanders | 阿盖尔和萨瑟兰高地人团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| armaments | 军备 | order | 4 | eligible | target | 需要目标#173 |
| arming_the_resistance | 武装抵抗 | order | 4 | eligible | target | 需要目标#180 |
| asw_patrol | 反潜巡逻 | order | 7 | eligible | direct | B#189(未特别指定) |
| at_all_cost | 不惜代价 | order | 3 | eligible | target | 需要目标#143 |
| atlantic_command | 大西洋航空指挥部 | order | 1 | eligible | direct | A#17 |
| atlantic_convoy | 大西洋护航队 | order | 3 | eligible | direct | B#107(未特别指定) |
| ats | 女子辅助军 | order | 3 | eligible | direct | B#108(未特别指定) |
| attack_in_the_colonies | 进攻殖民地 | order | 4 | eligible | target | 需要目标#193 |
| attrition | 消耗战 | order | 2 | eligible | target | 需要目标#118 |
| audacity | 无所畏惧 | order | 3 | eligible | direct | B#113(未特别指定) |
| aunt_frieda | 弗里达阿姨手册 | order | 1 | disabled | blacklist | 需要目标#39 |
| avro_anson | 安森 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| awoken_giant | 巨人苏醒 | order | 1 | eligible | target | B#16 用户指定 |
| b17_flying_fortress | B-17 飞行堡垒 | bomber | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b17f | B-17F | bomber | 10 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b24_liberator | B-24 解放者 | bomber | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b24d | B-24D | bomber | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b24j | B-24J | bomber | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b25_h | B-25 H | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b25_mitchell | B-25 米切尔 | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b26_groupe_bretagne | B-26 布列塔尼大队 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b26_marauder | B-26 掠夺者 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b29_superfortress | B-29 超级堡垒 | bomber | 12 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b4_203mm_howitzer | 203 毫米榴弹炮 | artillery | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b5n_kate | B5N 九七舰攻 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b6n_tenzan | B6N 天山舰攻 | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| b7a2_ryusei | B7A2 流星改 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| baker_street_irregulars | 贝克街分队 | order | 1 | disabled | hand_choice | B#36 用户指定 |
| balloon_bombs | 气球炸弹 | order | 0 | eligible | direct | A#5 |
| baltimore_mk_iii | 巴尔的摩 Mk III | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| baluch_regiment | 俾路支团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| banzai | 万岁冲锋 | order | 6 | eligible | direct | A#134 |
| barracuda | 梭鱼 | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| barrage | 弹幕 | order | 2 | disabled | unmarked_choice | 抉择#15:不在白名单里 |
| battery | 炮火支援 | order | 4 | eligible | target | 需要目标#183 |
| battle_mk_i_pl | 巴特尔 Mk I PL | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| battle_valor | 勇气迸发 | order | 5 | disabled | blacklist | B#164 用户指定 |
| beaufighter_tf_mk_x | 英俊战士 TF Mk X | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| beaufighter_vi_f | 英俊战士 Mk VI F | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bergmann_battalion | 山地人营 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| beriev_be4 | 别-4 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| betasom | 波尔多潜艇指挥部 | order | 2 | eligible | direct | B#69(未特别指定) |
| bf_109e7_trop | Bf 109 E-7 热带型 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bf_110_c_zerstrer | Bf 110 C | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| big_red_one | 大红一师 | infantry | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bl_4_5_medium_gun | 4.5 英寸中型火炮 | artillery | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| black_prince | A43 黑王子 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| black_watch | 黑卫士兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| blackburn_skua_mk_ii | 贼鸥 Mk II | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| blackout | 灯火管制 | order | 1 | disabled | blacklist | 需要目标#58 |
| blade_of_the_samurai | 武士之刃 | order | 6 | eligible | target | 需要目标#202 |
| blast | 爆破 | order | 0 | eligible | target | 需要目标#14 |
| blenheim_mk_i | 布伦亨 Mk I | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| blenheim_mk_iv | 布伦亨 Mk IV | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bletchley_park | 布莱切利庄园 | order | 12 | eligible | direct | A#163 |
| blitz_doctrine | 闪击战法 | order | 2 | eligible | three | B#89 用户指定 |
| blitzkrieg | 闪电战 | order | 3 | eligible | direct | A#87 |
| bloch_mb_152 | 布洛克 MB.152 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| blockade | 封锁 | order | 5 | eligible | direct | A#126 |
| blohm_voss_bv_138 | Bv 138 海龙 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| blood_red_sky | 血洒长空 | order | 2 | eligible | direct | A#61 |
| bloody_eleventh | 血腥第十一团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bloody_sickle | 血红镰刀 | order | 1 | eligible | target | 需要目标#70 |
| blue_and_gray | 蓝灰师 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| blue_legion | 蓝色军团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| blue_sky | 蓝天 | order | 0 | eligible | three | A#7 L147 用户指定:同上 |
| bm13n_us6 | BM-13N US6 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bocage_warfare | 篱墙之战 | order | 1 | eligible | target | B#33 用户指定 |
| bolster_the_ranks | 激励部队 | order | 4 | eligible | target | 需要目标#182 |
| bomber_mafia | 轰炸机黑手党 | order | 4 | eligible | three | B#151 用户指定 |
| bomber_run | 轰炸航路 | order | 2 | eligible | target | 需要目标#133 |
| bombing_raid | 轰炸突袭 | order | 4 | eligible | target | 需要目标#192 |
| bp43_armored_train | BP-43 装甲列车 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bpf | 英国太平洋舰队 | order | 2 | eligible | three | B#75 用户指定 |
| breaking_point | 临界点 | order | 2 | disabled | blacklist | 需要目标#83 |
| breakout | 突围 | order | 1 | disabled | blacklist | 需要目标#65 |
| breakthrough | 突破 | order | 3 | eligible | target | 需要目标#164 |
| breda_ba_65 | 布雷达 Ba.65 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| brewster_f2a | F2A 水牛 | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| brute_force | 蛮力 | order | 2 | eligible | target | 需要目标#132 |
| bryansk_irregulars | 布良斯克游击队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bt7 | BT-7 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bt7_1937 | BT-7 1937 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| bt7_1937_vet | BT-7 1937 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| buffs | 米色团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| burning_sky | 燃烧的天空 | order | 1 | disabled | blacklist | 需要目标#59 |
| burning_sun | 烈日 | order | 3 | eligible | direct | A#80 |
| burst_of_fire | 火力爆发 | order | 1 | disabled | blacklist | 需要目标#57 |
| buzz_bomb | 嗡嗡炸弹 | order | 1 | eligible | target | 需要目标#31 |
| by_the_sword | 以剑之名 | order | 4 | eligible | direct | A#93 |
| bypass | 迂回 | order | 5 | eligible | target | 需要目标#200 |
| c47_skytrain | C-47 空中列车 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| c6n_saiun | C6N 彩云舰侦 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| cadet_nurse_corps | 军校护士团 | order | 3 | eligible | direct | A#73 |
| call_to_the_colonies | 呼叫殖民地 | order | 4 | eligible | choice | 抉择#28 白名单:两个选项 / 选左边 |
| calliope | T34 风琴 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| calm_before_the_storm | 暴风雨前的宁静 | order | 4 | eligible | direct | A#105 |
| cameronians | 卡梅伦团 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| campaign_trail | 战役路线 | order | 4 | eligible | direct | A#103 |
| cannone_da_47 | 47 毫米反坦克炮 | artillery | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| capitulation | 一触即溃 | order | 9 | eligible | direct | A#155 |
| caproni_ca_133 | 卡普罗尼 Ca.133 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| careless_talk | 无心漫谈 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| carpet_bombing | 地毯式轰炸 | order | 7 | eligible | direct | A#145 |
| carrier_battle | 航母战 | order | 3 | eligible | target | A#84 L239 用户指定:同快速胜利 |
| carrier_cover | 航母掩护 | order | 1 | eligible | choice | 抉择#9 白名单:两个选项 / 选右边 |
| case_blue | 蓝色方案 | order | 9 | eligible | target | 需要目标#213 |
| case_yellow | 黄色方案 | order | 5 | eligible | target | B#175 用户指定 |
| cedar_division | 杉兵团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| cedar_division_vet | 杉兵团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| chain_home | 本土链 | order | 2 | eligible | target | 需要目标#111 |
| char_b1_bis | B1 重型坦克 II 型 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| chasing_shadows | 捕风捉影 | order | 0 | eligible | target | 需要目标#10 |
| cheshire_regiment | 柴郡团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| churchill_mk_iii_avre | 丘吉尔 Mk III AVRE | tank | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| churchill_mk_iv | 丘吉尔 Mk IV | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| claim_objective | 夺取目标 | order | 2 | eligible | direct | B#56(未特别指定) |
| claim_the_skies | 夺取制空 | order | 1 | eligible | target | B#13 用户指定 |
| close_air_support | 近距离空中支援 | order | 1 | disabled | blacklist | 需要目标#74 |
| close_call | 千钧一发 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| close_combat | 短兵相接 | order | 2 | eligible | direct | A#54 |
| coastal_battalion_7 | 第 7 海岸步兵营 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| coastwatchers | 海岸观察员 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| cobelligerents | 战时盟国 | order | 7 | eligible | target | B#191 用户指定 |
| code_of_bushido | 武士道准则 | order | 3 | disabled | blacklist | 需要目标#155 |
| cold_trap | 极寒陷阱 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| coldstream_guards | 冷溪卫队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| colonial_dreams | 殖民梦 | order | 1 | eligible | direct | A#28 |
| colossus | 巨人计算机 | order | 1 | eligible | direct | B#17(未特别指定) |
| combined_arms | 协同作战 | order | 1 | disabled | blacklist | 需要目标#29 |
| combined_chiefs_of_staff | 参谋长联席会议 | order | 6 | eligible | direct | A#139 |
| command_failure | 指挥不当 | order | 3 | disabled | blacklist | 需要目标#152 |
| commando_raid | 突击队突击 | order | 6 | eligible | direct | A#142 |
| commandos_kieffer | 基弗突击队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| commit_the_reserves | 穷兵黩武 | order | 2 | disabled | blacklist | 需要目标#122 |
| committed_crew | 恪尽职守 | order | 10 | eligible | direct | A#160 |
| compromise | 妥协 | order | 4 | eligible | choice | 抉择#29 白名单:两个选项 / 选右边 |
| confusion | 混乱 | order | 3 | disabled | blacklist | B#116 用户指定 |
| conquest | 征服 | order | 2 | unreviewed | unreviewed | 无需手动目标的抽牌候选；需确认当前友方类型数、抽牌收益及手牌容量，尚未放行。 |
| conscripts | 征召兵 | order | 2 | eligible | direct | B#60(未特别指定) |
| contest_doctrine | 竞争战法 | order | 4 | eligible | three | B#149 用户指定 |
| convoy_attack | 护航攻击 | order | 0 | eligible | target | 需要目标#8 |
| convoy_hx_175 | HX 175 护航队 | order | 3 | eligible | direct | A#68 |
| corps_command | 军司令部 | order | 4 | unreviewed | unreviewed | 还没归类 |
| corsair_f4u1c | F4U-1C 海盗 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| corsair_f4u1d | F4U-1D 海盗 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| costly_victory | 惨胜 | order | 5 | eligible | target | 需要目标#197 |
| counter_offensive | 反击攻势 | order | 2 | eligible | target | 需要目标#93 |
| counter_strike | 反袭 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| counterattack | 反击 | order | 3 | eligible | direct | B#104(未特别指定) |
| covert_operation | 秘密行动 | order | 5 | eligible | direct | B#172(未特别指定) |
| creeping_barrage | 徐进弹幕 | order | 2 | eligible | target | 需要目标#100 |
| critical_damage | 致命伤害 | order | 1 | eligible | target | 需要目标#67 |
| critical_hit | 致命一击 | order | 4 | disabled | blacklist | 需要目标#190 |
| cromwell_mk_iv | 克伦威尔 Mk IV | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| cross_of_lorraine | 洛林十字 | order | 9 | eligible | target | 需要目标#212 |
| crossfire | 交叉火力 | order | 5 | eligible | direct | A#119 |
| cruiser_mk_iii | 巡航坦克 Mk III | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| cruiser_scouts | 巡洋舰侦察机 | order | 3 | unreviewed | follow | 需要目标#98 两步:1 -> 7 |
| crusader_mk_ii | 十字军 Mk II | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| cup_of_tea | 一杯茶 | order | 1 | eligible | direct | A#10 |
| cyclone | 旋风 | order | 6 | conditional | weather_variant_required | 纯名称不放行；须当前描述解析独立天气版本并再次复核。 |
| cyclone_division | 龙卷师 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| cyclone_division_vet | 龙卷师 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| d4y_suisei | D4Y 彗星舰爆 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| danuta | 达努塔装甲列车 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| daring_strike | 英勇一击 | order | 4 | eligible | target | 需要目标#191 |
| dark_deeds | 阴谋 | order | 1 | eligible | direct | B#41(未特别指定) |
| dawn_operations | 拂晓行动 | order | 2 | eligible | direct | B#64(未特别指定) |
| daylight_bombing | 日间轰炸 | order | 4 | eligible | target | 需要目标#179 |
| deadly_duty | 极限使命 | order | 1 | eligible | target | 需要目标#51 |
| death_from_above | 死神降临 | order | 4 | eligible | direct | B#142(未特别指定) |
| decisive_defense | 关键防御 | countermeasure | 3 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| decoy_tactics | 诱饵战术 | order | 3 | eligible | target | 需要目标#166 |
| deep_operation | 大纵深作战 | order | 2 | eligible | direct | A#37 |
| defeat_in_detail | 逐个击破 | order | 1 | eligible | direct | A#33 |
| defend_in_depth | 纵深防御 | order | 3 | eligible | target | 需要目标#165 |
| defend_the_nation | 保家卫国 | order | 1 | eligible | direct | A#12 |
| defiant_mk_i | 无畏 Mk I | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| delaying_tactics | 拖延战术 | order | 2 | eligible | direct | A#41 |
| deluge | 暴雨 | order | 2 | conditional | weather_variant_required | 纯名称不放行；须当前描述解析独立天气版本并再次复核。 |
| depot_raid | 劫营 | order | 4 | eligible | target | B#128 用户指定 |
| depth_charges | 深水炸弹 | order | 0 | eligible | direct | B#4(未特别指定) |
| depths_of_winter | 严冬 | order | 5 | eligible | direct | A#117 |
| desert_dust | 沙尘满目 | order | 3 | eligible | target | 需要目标#156 |
| desert_push | 沙漠推进 | order | 1 | eligible | target | B#26 用户指定 |
| desert_raid | 沙漠突袭 | order | 2 | eligible | direct | A#46 |
| desperate_measures | 亡命之计 | order | 2 | eligible | direct | B#47(未特别指定) |
| detached_battalion_4 | 第 4 独立大队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| detailed_recon | 周密侦察 | order | 4 | eligible | direct | B#130(未特别指定) |
| devils_brigade | 魔鬼旅 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| dewoitine_d_520 | 地瓦丁 D.520 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| dilemma | 两难困境 | order | 1 | eligible | target | B#9 用户指定 |
| dingo | 丁格犬侦察车 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| diplomatic_attach | 外交专员 | order | 1 | eligible | target | 需要目标#36 |
| direct_hit | 直接命中 | order | 1 | eligible | target | 需要目标#62 |
| distant_front | 鞭长莫及 | order | 1 | eligible | target | B#43 用户指定:仅 3 攻以下 |
| dive_bombing | 俯冲轰炸 | order | 1 | eligible | target | 需要目标#24 |
| diversion | 转移目标 | order | 2 | eligible | target | B#84 用户指定:仅非守护单位 |
| divine_wind | 神风行动 | order | 3 | eligible | target | 需要目标#161 |
| do_or_die | 拼死一搏 | order | 2 | eligible | direct | B#65(未特别指定) |
| dornier_do_17z | Do 17 Z | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| dornier_do_18g | Do 18 G | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| dornier_do_217 | Do 217 | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| double_strength | 双倍力量 | order | 1 | eligible | direct | B#11(未特别指定) |
| dowding_system | 道丁系统 | countermeasure | 3 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| drive_into_the_sea | 驱敌入海 | order | 3 | eligible | target | B#124 用户指定 |
| duck | J2F 鸭式 | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| dug_in | 深挖 | order | 0 | eligible | target | 需要目标#13 |
| duress | 胁迫 | order | 0 | eligible | target | B#6 用户指定 |
| duty_bound | 责无旁贷 | order | 1 | eligible | target | 需要目标#73 |
| duty_is_a_mountain | 义重如山 | order | 6 | eligible | direct | A#135 |
| e13a_jake | E13A 零式水侦 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| eagle_claws | 鹰爪 | order | 3 | eligible | direct | A#89 |
| eagle_day | 鹰日计划 | order | 5 | disabled | blacklist | B#174 用户指定 |
| east_surrey_regiment | 东萨里团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| eastern_front_bound | 东线边界 | order | 3 | eligible | direct | B#99(未特别指定) |
| echelon | 梯队 | order | 2 | eligible | direct | A#43 |
| edge_of_the_empire | 帝国边境 | order | 2 | eligible | direct | A#39 |
| elusive_force | 潜在力量 | order | 2 | eligible | direct | A#49 |
| embargo | 禁止通商 | order | 2 | eligible | direct | A#55 |
| emergency_measures | 紧急措施 | order | 2 | eligible | direct | B#74(未特别指定) |
| empire_of_the_sun | 太阳帝国 | order | 9 | eligible | target | 需要目标#211 |
| encirclement | 包围 | order | 3 | disabled | blacklist | B#103 用户指定 |
| enemy_at_the_gates | 兵临城下 | order | 4 | eligible | direct | A#96 |
| enemy_contact | 逢敌 | order | 2 | eligible | target | 需要目标#136 |
| enemy_sighted | 目击敌人 | order | 5 | eligible | target | 需要目标#198 |
| enemy_spotted | 发现敌人 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| engage_at_range | 远距离交战 | order | 2 | eligible | target | 需要目标#135 |
| engage_up_close | 近距离交战 | order | 2 | eligible | target | 需要目标#134 |
| enigma | 恩尼格玛 | order | 4 | eligible | direct | A#101 |
| entanglement | 障碍 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| entrapment | 圈套 | countermeasure | 5 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| entrenched | 深沟固垒 | order | 2 | disabled | blacklist | 需要目标#119 |
| envelop | 合围 | countermeasure | 3 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| escaut_plan | 埃斯科计划 | order | 1 | eligible | target | 需要目标#35 |
| escort_group | 护航船队 | order | 3 | disabled | unmarked_choice | 抉择#22:不在白名单里 |
| evasive_action | 规避动作 | countermeasure | 0 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| exhaust_all_options | 竭尽全力 | order | 4 | eligible | target | 需要目标#187 |
| exiled_forces | 流亡部队 | order | 5 | eligible | target | B#168 用户指定 |
| expanded_imperial_rd | 扩展帝国研发 | order | 6 | eligible | choice | 抉择#32 白名单:两个选项 / 选右边 |
| expanded_reich_rd | 扩展德意志帝国研发 | order | 6 | eligible | choice | 抉择#33 白名单:两个选项 / 选右边 |
| expanded_royal_research | 扩展皇家研发 | order | 6 | disabled | unmarked_choice | 抉择#34:不在白名单里 |
| expanded_soviet_research | 扩展苏联研发 | order | 6 | eligible | choice | 抉择#36 白名单:两个选项 / 选右边 |
| expanded_us_research | 扩展美国研发 | order | 6 | eligible | choice | 抉择#35 白名单:两个选项 / 选右边 |
| expansion | 扩张 | order | 1 | eligible | direct | A#24 |
| expeditionary_corps | 远征军 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| experimental_flight | 试验飞行 | order | 1 | disabled | hand_choice | B#35 用户指定 |
| exploit_the_gap | 扩大优势 | order | 6 | disabled | blacklist | 需要目标#201 |
| exposed | 暴露无遗 | order | 1 | disabled | blacklist | 需要目标#49 |
| extended_barrage | 持续弹幕 | order | 2 | eligible | target | 需要目标#107 |
| f1m2_pete | F1M2 零式水观 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| f4f3_wildcat | F4F-3 野猫 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| f4f4_wildcat | F4F-4 野猫 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| f6f3_hellcat | F6F-3 地狱猫 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| f6f5_hellcat | F6F-5 地狱猫 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| farman_f_222 | 法尔芒 F.222 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fast_heinz | 古德里安 | order | 1 | eligible | direct | A#15 |
| feigned_retreat | 假装撤退 | order | 6 | eligible | direct | B#176(未特别指定) |
| feldherrnhalle_rifles | 统帅堂装甲掷弹兵师 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ferocious_assault | 猛袭 | order | 2 | unreviewed | unreviewed | 判为需要目标,但还没给它规格 需步兵目标、当前属性及指挥点槽关联收益。 |
| fiat_br_20 | 菲亚特 BR.20 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fiat_c_r_32 | 菲亚特 C.R.32 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fiat_c_r_42 | 菲亚特 C.R.42 | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fiat_g_50 | 菲亚特 G.50 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fiat_g_50_fi | 菲亚特 G.50 FI | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fiat_g_55 | 菲亚特 G.55 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| field_hospital | 野战医院 | order | 4 | eligible | direct | B#153(未特别指定) |
| field_recon | 野外侦察 | order | 2 | disabled | blacklist | 需要目标#137 |
| fiery_ambush | 猛烈伏击 | order | 3 | eligible | target | 需要目标#159 |
| fieseler_fi_156 | Fi 156 鹳式 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fifth_ohio | 俄亥俄州第 5 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| final_push | 最后一击 | order | 1 | eligible | target | 需要目标#50 |
| finest_hour | 最光辉的时刻 | order | 2 | disabled | blacklist | 需要目标#110 |
| finnish_boys | 芬兰男孩步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| firebomb | 燃烧弹 | order | 4 | eligible | target | 需要目标#184 |
| firewall | 防火墙 | order | 2 | eligible | target | 需要目标#138 |
| first_responders | 第一响应 | countermeasure | 3 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| first_to_fight | 冲锋在前 | order | 2 | eligible | target | 需要目标#90 |
| five_year_plan | 五年计划 | order | 5 | eligible | direct | A#118 |
| flammpanzer | 喷火坦克 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| flight_to_oblivion | 终焉之行 | order | 3 | eligible | direct | B#119(未特别指定) |
| focused_attack | 集中攻击 | order | 6 | eligible | direct | B#187(未特别指定) |
| fog_of_war | 战争迷雾 | order | 4 | eligible | target | B#137 用户指定 |
| foiled_plans | 轻虑浅谋 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| fokker_d_xxi | 福克 D.XXI | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| for_freedom | 为了自由 | order | 1 | eligible | target | 需要目标#20 |
| for_glory | 为了荣耀 | order | 2 | disabled | blacklist | 需要目标#85 |
| for_prosperity | 为了繁荣 | order | 2 | eligible | direct | A#34 |
| for_the_emperor | 为了帝国 | order | 1 | eligible | direct | A#11 |
| for_the_king | 为了国王 | order | 2 | disabled | blacklist | 需要目标#84 |
| forced_surrender | 逼迫投降 | order | 1 | eligible | target | 需要目标#75 |
| forged_in_fire | 千锤百炼 | order | 2 | eligible | target | 需要目标#92 |
| form_battle_line | 形成战线 | order | 4 | disabled | unmarked_choice | 抉择#31:不在白名单里 |
| fortification | 防御工事 | order | 3 | eligible | direct | A#88 |
| fortified_position | 加固阵地 | order | 1 | eligible | target | 需要目标#28 |
| fortunes_of_war | 战争财 | order | 3 | disabled | blacklist | B#110 用户指定 |
| forward_base | 前沿基地 | order | 2 | unreviewed | unreviewed | 判为需要目标,但还没给它规格 需最左手牌身份/费用及后续单位目标。 |
| forward_observers | 前进观察员 | order | 4 | eligible | direct | B#127(未特别指定) |
| frappe | 攻击 | order | 1 | disabled | blacklist | 需要目标#46 |
| free_french_navy | 自由法国海军 | order | 2 | eligible | direct | A#60 |
| french_75 | 75 毫米野战炮 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fresh_recruits | 新兵入伍 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| friendly_fire | 误伤 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| from_the_deep | 来自深处 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| from_the_people | 来自人民 | order | 3 | eligible | target | 需要目标#153 |
| front_and_homeland | 前线与家乡 | order | 4 | eligible | direct | A#97 |
| front_formation | 方面军 | order | 9 | eligible | direct | B#198(未特别指定) |
| frontal_assault | 正面突击 | order | 2 | eligible | direct | A#45 |
| frontal_defense | 正面防御 | order | 1 | eligible | target | 需要目标#53 |
| frontier_force | 边防团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| frozen_assets | 强制冻结 | order | 4 | eligible | direct | B#136(未特别指定) |
| fukuoka_regiment | 福冈联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| furor | 狂怒 | order | 1 | disabled | blacklist | 黑名单同族「狂怒」:用户点名别带 |
| fw_189 | Fw 189 鸮鹰 | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fw_190_a | Fw 190 A 百舌鸟 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fw_190_f9 | Fw 190 F-9 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fw_190_jagdbomber | Fw 190 A-3/U3 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fw_200_condor | Fw 200 秃鹰 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fw_ta_152 | Ta 152 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| fw_ta_152_vet | Ta 152 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| g4m1_betty | G4M1 一式陆攻 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| gale | 狂风 | order | 0 | eligible | three | A#6 L146 用户指定:新的天气牌,打出后弹三张卡三选一 |
| gambit | 博弈 | order | 5 | eligible | direct | A#123 |
| garrison | 卫戍 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| gathering_storm | 风暴前夕 | order | 8 | eligible | direct | B#197(未特别指定) |
| gebirgspionier_95 | 第 95 山地工兵营 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| gifu_regiment | 岐阜联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| gladiator_escort | 角斗士护航机 | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| gladiator_mk_i | 角斗士 Mk I | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| glide_bombing | 滑翔轰炸 | order | 2 | eligible | target | 需要目标#120 |
| gordon_highlanders | 戈登高地人团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| grand_plans | 好高骛远 | order | 1 | disabled | hand_choice | B#14 用户指定 |
| great_patriotic_war | 伟大的卫国战争 | order | 6 | eligible | direct | A#137 |
| greater_purpose | 远大目标 | order | 4 | eligible | direct | B#152(未特别指定) |
| green_howards | 绿色霍华德团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| greif | 狮鹫指挥车 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| grenadier_guards | 掷弹兵卫队 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| grim_day | 朝不保夕 | order | 1 | eligible | direct | B#24(未特别指定) |
| grounded | 停飞 | order | 5 | eligible | target | B#162 用户指定 |
| grumman_goose | G-21 鹅式 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| guerilla_warfare_school | 游击战学校 | order | 1 | eligible | direct | B#28(未特别指定) |
| gunboat_hit | 炮艇命中 | order | 1 | eligible | target | B#30 用户指定 |
| gunboat_raid | 炮艇突袭 | order | 4 | eligible | target | B#145 用户指定 |
| gunboat_run | 炮艇出击 | order | 1 | eligible | direct | A#32 |
| gunship_mission | 炮艇任务 | order | 2 | eligible | target | B#71 用户指定 |
| h39_swg | H39 sWG | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| h75c1 | 柯蒂斯 H75-C1 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| halifax_b_mk_i | 哈利法克斯 B Mk I | bomber | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hammer_home | 捷报传乡 | order | 4 | disabled | blacklist | B#138 用户指定 |
| hampden_mk_i | 汉普敦 Mk I | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hampshire_regiment | 汉普郡团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| happy_time | 美好时光 | order | 4 | eligible | three | 需要目标#189 |
| harass | 侵扰 | order | 3 | eligible | target | B#100 用户指定 |
| hasty_reinforcements | 急速增援 | order | 1 | eligible | direct | B#19(未特别指定) |
| heartland_defense | 腹地防御 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| heatwave | 热浪 | order | 2 | conditional | weather_variant_required | 纯名称不放行；须当前描述解析独立天气版本并再次复核。 |
| heinkel_he_111 | He 111 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| heinkel_he_115 | He 115 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| heinkel_he_219 | He 219 夜枭 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| heinkel_he_59 | He 59 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hel | 海尔要塞 | order | 2 | disabled | blacklist | 需要目标#116 |
| hell_on_wheels | 地狱之轮 | order | 4 | eligible | direct | B#131(未特别指定) |
| henschel_hs_123 | Hs 123 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| henschel_hs_126 | Hs 126 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| henschel_hs_129 | Hs 129 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| heroes_of_the_soviet_union | 苏联英雄 | order | 2 | eligible | three | 需要目标#131 |
| hidden_plans | 保密计划 | order | 1 | disabled | unmarked_choice | 抉择#2:不在白名单里 |
| high_altitude_bombing | 高空轰炸 | order | 8 | eligible | direct | A#154 |
| himeji_regiment | 姬路联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hirosaki_brigade | 弘前旅团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| his_majestys_chosen | 皇家旨意 | order | 2 | eligible | three | 需要目标#121 |
| hit_the_drop_point | 袭击落点 | countermeasure | 0 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| hmas_warramunga | HMAS 瓦拉孟加号 | order | 0 | disabled | hand_choice | 需要目标#1 |
| hms_belfast | HMS 贝尔法斯特号 | order | 4 | eligible | target | B#126 用户指定 |
| hms_formidable | HMS 可畏号 | order | 4 | eligible | target | 需要目标#169 |
| hms_hermes | HMS 竞技神号 | order | 6 | eligible | direct | A#133 |
| hms_illustrious | HMS 光辉号 | order | 3 | eligible | direct | A#67 |
| hms_sceptre | HMS 权杖号 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| hms_talbot | HMS 塔尔伯特 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| hold_the_line | 坚守阵线 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| home_defense | 本土决战 | order | 8 | eligible | direct | A#151 |
| home_guard | 国土警卫队 | order | 1 | eligible | target | 需要目标#33 |
| honor | 玉碎 | order | 3 | eligible | target | 需要目标#160 |
| honor_and_loyalty | 荣誉与忠诚 | order | 1 | eligible | direct | B#34(未特别指定) |
| honorable_death | 光荣死亡 | order | 1 | disabled | blacklist | 需要目标#26 |
| honorifics | 荣誉称号 | order | 2 | eligible | target | B#76 用户指定 |
| hotchkiss_h35 | 哈奇开斯 H35 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hudson_mk_iii | 哈德逊 Mk III | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hull_down | 车体隐蔽 | order | 2 | disabled | blacklist | B#82 用户指定:仅坦克 |
| human_torpedo | 人控鱼雷 | order | 5 | eligible | target | B#161 用户指定 |
| humber_mk_ii | 亨伯 Mk II | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| humber_mk_iv | 亨伯 Mk IV | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hummel | 野蜂式自行火炮 | artillery | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hurricane_mk_i | 飓风 Mk I | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hurricane_mk_iia | 飓风 Mk IIa | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hurricane_mk_iic_trop | 飓风 Mk IIc 热带型 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hurricane_mk_iic_trop_vet | 飓风 Mk IIc 热带型 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| hurricane_pl | 飓风 PL | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| i15_chaika | 伊-15 海鸥 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| i16_ishak | 伊-16 毛驴 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| i_stridsgruppen | 第 1 战斗群 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ijn_akagi | IJN 赤城号 | order | 4 | eligible | direct | A#91 |
| ijn_mikura | IJN 御藏号 | order | 1 | eligible | target | 需要目标#18 |
| ijn_shinano | IJN 信浓号 | order | 3 | eligible | direct | B#95(未特别指定) |
| ijn_shirakumo | IJN 白云号 | order | 2 | eligible | target | 需要目标#79 |
| ijn_yamato | IJN 大和号 | order | 10 | eligible | direct | A#157 |
| il2m_pl | 伊尔-2M PL | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ilyushin_il10 | 伊尔-10 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ilyushin_il2 | 伊尔-2 | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| imperial_decree | 诏令 | order | 0 | eligible | direct | A#2 |
| imperial_order | 帝国指令 | order | 1 | eligible | target | B#18 用户指定 |
| imperial_research | 帝国研发 | order | 3 | eligible | choice | 抉择#20 白名单:两个选项 / 选右边 |
| imperial_strength | 帝国之力 | order | 1 | eligible | direct | A#22 |
| imperial_weapon_no_2 | 皇国二号兵器 | order | 12 | eligible | direct | A#165 |
| in_hour_of_need | 战争需要 | order | 4 | eligible | direct | A#102 |
| in_the_navy | 海军服役 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| industrial_might | 工业力量 | order | 2 | eligible | direct | B#57(未特别指定) |
| infantry_regiment_11 | 第 11 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| infantry_regiment_13 | 第 13 步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| infantry_regiment_2 | 第 2 步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| infantry_regiment_25 | 第 25 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| infantry_regiment_36 | 第 36 步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| infantry_regiment_56 | 第 56 步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| infantry_regiment_61 | 第 61 步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| infiltrate | 渗透 | order | 5 | eligible | direct | B#169(未特别指定) |
| ingenuity | 革新 | order | 2 | eligible | three | B#94 用户指定 |
| inniskilling_fusiliers | 因尼斯基林燧发枪兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| interception | 拦截 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| iosef_stalin_ii | IS-2 | tank | 10 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| irish_guards | 爱尔兰卫队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| iron_division | 钢铁师 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| iron_from_the_north | 北方铁矿 | order | 1 | eligible | direct | A#14 |
| iron_victory | 百炼成钢 | order | 5 | eligible | direct | B#171(未特别指定) |
| irregular_recruits | 非常规兵员 | order | 1 | eligible | direct | B#42(未特别指定) |
| is_ii_1944_early | IS-2 1944 早期型 | tank | 10 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| island_defense | 岛屿防御 | order | 4 | eligible | direct | B#134(未特别指定) |
| island_hopping | 跳岛战术 | order | 3 | eligible | direct | B#121(未特别指定) |
| isolation | 孤立 | order | 1 | eligible | target | B#15 用户指定 |
| isu152 | ISU-152 | tank | 9 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ita_regiment | 大分联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| j1n1_gekko | J1N1 月光夜战 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| j2m_raiden | J2M 雷电局地战 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| jade_division | 玉兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| jagdpanther | 猎豹 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| jagdpanzer_iv | 四号坦克歼击车 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| jet_prototype | 喷气机原型机 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| jger_battalion_2 | 第 2 猎兵营 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| joint_operation | 联合行动 | order | 2 | eligible | target | 需要目标#129 |
| ju_87_b2 | Ju 87 B-2 斯图卡 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ju_87_b_stuka | Ju 87 B 斯图卡 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ju_88_g6 | Ju 88 G-6 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| juggernaut | 主宰者 | order | 1 | disabled | blacklist | 需要目标#21 |
| jungle_fever | 丛林热 | order | 4 | conditional | weather_variant_required | 纯名称不放行；须当前描述解析独立天气版本并再次复核。 |
| jungle_warfare | 丛林战 | order | 4 | eligible | target | 需要目标#172 |
| junkers_ju_188_e | Ju 188 E 复仇者 | bomber | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| junkers_ju_88_a | Ju 88 A | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kagoshima_regiment | 布干维尔守备队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kamikaze | 神风特攻队 | order | 1 | eligible | direct | B#32(未特别指定) |
| kanazawa_regiment | 金泽联队 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kangaroo_transport | 袋鼠运输 | order | 1 | disabled | blacklist | 需要目标#71 |
| katalina | 卡特琳娜 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| katyusha | 喀秋莎 | artillery | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| katzmann_regiment | 卡茨曼团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kawanishi_e7k | E7K 九四水侦 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kawanishi_h6k | H6K 九七大艇 | bomber | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kawanishi_h8k | H8K 二式大艇 | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kawasaki_ki10 | Ki-10 九五战 | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kettenkrad | 轻型履带摩托车 | order | 2 | eligible | direct | B#85(未特别指定) |
| kfu_regiment | 甲府联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki100_goshikisen | Ki-100 五式战 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki21_sally | Ki-21 九七重爆 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki27_nate | Ki-27 九七战 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki30_ann | Ki-30 九七轻爆 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki43_hayabusa | Ki-43 一式战 隼 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki43iib_otsu | Ki-43 一式战二型乙 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki44_tojo | Ki-44 二式战 钟馗 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki45_dragon_slayer | Ki-45 二式复战 屠龙 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki45_dragon_slayer_vet | Ki-45 二式复战 屠龙 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki46_dinah_iii | Ki-46 百式司侦 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki49_storm_dragon | Ki-49 百式重爆 吞龙 | bomber | 9 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki51_sonia | Ki-51 九九轻爆 | bomber | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki61_hien | Ki-61 三式战 飞燕 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki61ii_tony | Ki-61 三式战改 飞燕 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki61itei | Ki-61-I 三式战一型丁 飞燕 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki67_peggy | Ki-67 四式重爆 飞龙 | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki83 | Ki-83 试制重战 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ki84_frank | Ki-84 四式战 疾风 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kikka | 试制橘花 | fighter | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| king_tiger | 虎王坦克 | tank | 12 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kingfisher | OS2U 翠鸟 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kings_african_rifles | 英王非洲步枪兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kings_own_scottish | 英王直属苏格兰边民团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| km_admiral_hipper | KM 希佩尔海军上将号 | order | 5 | eligible | target | B#157 用户指定 |
| km_bismarck | KM 俾斯麦号 | order | 10 | eligible | target | 需要目标#214 |
| km_prinz_eugen | KM 欧根亲王号 | countermeasure | 4 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| km_tirpitz | KM 提尔皮茨号 | order | 5 | eligible | direct | A#115 |
| kokuras_sword | 剑兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| komet | Me 163 彗星 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kriegsmarine | 战争海军 | order | 7 | eligible | direct | B#190(未特别指定) |
| kumamoto_regiment | 所罗门守备队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kurmark_aufklrung | 库尔马克侦察营 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kurume_regiment | 久留米联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kv1_1939 | KV-1 1939 | tank | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kv1_1941 | KV-1 1941 | tank | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kv1s | KV-1S | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kv2 | KV-2 | tank | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kv85 | KV-85 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kyoto_regiment | 京都联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| kyushu_j7w3 | J7W3 震电局地战 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| l4_grasshopper | L-4 蚱蜢 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| l640 | L6/40 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| la5 | 拉-5 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| la_decima | 第 10 快艇支队 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| la_division_leclerc | 勒克莱尔师 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| lancashire_fusiliers | 兰开夏燧发枪兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| lancaster_b_iii | 兰开斯特 B.III | bomber | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| lancaster_mk_i | 兰开斯特 Mk I | bomber | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| land_of_the_free | 自由之地 | order | 1 | eligible | target | 需要目标#66 |
| last_ditch_force | 最后一搏 | order | 10 | unreviewed | unreviewed | 还没归类 |
| last_rites | 最后的仪式 | order | 3 | eligible | direct | A#77 |
| layforce | 莱福斯突击队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| legions | 军团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| lend_lease | 租借法案 | order | 7 | eligible | direct | A#146 |
| leopold | 利奥波德 | artillery | 10 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| les_terribles | 骇人步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| lesser_of_two_evils | 权衡 | order | 2 | disabled | hand_choice | B#68 用户指定 |
| liberation | 解放 | order | 3 | eligible | direct | A#86 |
| light_detachment_15 | 第 15 轻步兵支队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| light_infantry | 轻步兵 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| lightning_conquest | 闪电征服 | order | 2 | eligible | direct | A#64 |
| lightning_strike | 闪电袭击 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| line_of_engagement | 交战线 | order | 2 | eligible | direct | B#48(未特别指定) |
| lion_for_a_day | 一日之狮 | order | 4 | eligible | target | 需要目标#171 |
| list_regiment | 利斯特步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| little_cobra | P-39 小蛇 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| london_irish_rifles | 伦敦爱尔兰步枪兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| long_lance | 氧气鱼雷 | order | 0 | eligible | target | 需要目标#12 |
| long_range_desert_group | 长距离沙漠群 | order | 5 | eligible | direct | A#132 |
| long_range_recon | 远距离侦察 | order | 4 | eligible | direct | A#112 |
| long_tom | 长腿汤姆 | artillery | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| lost_convoy | 护航覆灭 | countermeasure | 0 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| lotta_svrd | 洛塔组织 | order | 2 | eligible | direct | A#48 |
| lovat_scouts | 洛瓦特侦察兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| lublin_rxiii | 卢布林 R-XIII | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| lure | 诱敌 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| lurking_danger | 潜在危险 | order | 1 | eligible | direct | A#31 |
| lysander_pl | 莱桑德 PL | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m10_wolverine | M10 狼獾 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m10a1 | M10A1 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m1340 | M13/40 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m16_halftrack | M16 半履带防空车 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m18_hellcat | M18 地狱猫 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m20_scout_car | M20 侦察车 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m24_chaffee | M24 霞飞 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m26_pershing | M26 潘兴 | tank | 10 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m2a4 | M2A4 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m36_jackson | M36 杰克逊 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m3_grant | M3 格兰特 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m3_lee | M3 李 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m3a3_honey | M3A3 甜心 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m4_firefly | M4 萤火虫 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m4_firefly_pl | M4 萤火虫 PL | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m4_sherman | M4 谢尔曼 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m4_sherman_pl | M4 谢尔曼 PL | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m4a1 | M4A1 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m4a2 | M4A2 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m4a3r3_zippo | M4A3R3 打火机 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m5_stuart | M5 斯图亚特 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m6 | M6 | tank | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m6a1_seiran | M6A1 晴岚特攻 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m7_priest | M7 牧师 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m8_greyhound | M8 灰狗 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m8_howitzer | M8 榴弹炮 | artillery | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| m_s_406 | 莫拉纳-索尼耶 M.S.406 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| macchi_c_200 | 马基 C.200 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| macchi_c_202 | 马基 C.202 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| macchi_c_205 | 马基 C.205 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| machines_of_war | 全民参战 | order | 5 | eligible | direct | B#163(未特别指定) |
| maelstrom | 大混战 | order | 8 | eligible | direct | A#149 |
| magic | 魔法 | order | 1 | disabled | unmarked_choice | 抉择#14:不在白名单里 |
| maginot_line | 马奇诺防线 | order | 3 | eligible | target | 需要目标#168 |
| magnificent_seventh | 第 7 陆战团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| manchester_ia | 曼彻斯特 Mk Ia | bomber | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| manhattan_project | 曼哈顿计划 | order | 6 | eligible | direct | B#183(未特别指定) |
| manpower | 人力 | order | 5 | eligible | target | B#160 用户指定 |
| maori_battalion | 毛利营 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| marder_iii_h | 黄鼠狼 III H 型 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mare_nostrum | 我们的海 | order | 1 | eligible | target | 需要目标#42 |
| mass_attack | 大规模攻击 | order | 4 | eligible | target | 需要目标#175 |
| mass_deployment | 大规模部署 | order | 10 | eligible | direct | A#159 |
| materials | 原料 | order | 4 | eligible | direct | A#99 |
| matilda_frog | 玛蒂尔达 蛙式 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| matilda_mk_ii | 玛蒂尔达 Mk II | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| matilda_mk_iv | 玛蒂尔达 Mk IV | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| matilda_mk_iv_vet | 玛蒂尔达 Mk IV | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| matsue_regiment | 松江联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| matsumoto_regiment | 松本联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| maus | 鼠式坦克 | tank | 12 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mayhem | 骚乱 | order | 4 | disabled | blacklist | B#156 用户指定 |
| me_262a_schwalbe | Me 262 A 飞燕 | fighter | 9 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| me_410_hornisse | Me 410 大黄蜂 | fighter | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| me_bf_109_e | Bf 109 E | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| me_bf_109_g | Bf 109 G | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| me_bf_109_g_fi | Bf 109 G FI | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| me_bf_110 | Bf 110 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| me_bf_110_e | Bf 110 E | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mediterranean_raid | 地中海突袭 | order | 3 | eligible | target | 需要目标#147 |
| men_of_steel | 钢铁之躯 | order | 1 | eligible | choice | 抉择#13 白名单:两个选项 / 选右边 |
| meteor | 流星 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mi5 | 军情五处 | order | 3 | eligible | direct | B#101(未特别指定) |
| middlesex_regiment | 米德尔塞克斯团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mig_3 | 米格-3 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mikawa_regiment | 丰桥联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| minority_recruits | 小国成员 | order | 10 | eligible | target | B#199 用户指定 |
| missing | 失踪 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| mist | 薄雾 | order | 0 | eligible | three | A#8 L148 用户指定:同上 |
| mito_regiment | 水户联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mobile_defense | 机动防御 | order | 2 | eligible | direct | A#42 |
| mobilization | 动员 | order | 2 | eligible | direct | A#35 |
| model_25 | 维克斯装甲车 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| molotov_cocktail | 莫洛托夫鸡尾酒 | order | 2 | eligible | direct | B#77(未特别指定) |
| momentum | 破竹之势 | order | 4 | eligible | direct | A#109 |
| monastyr | 修道院行动 | order | 8 | eligible | direct | A#148 |
| monsoon_rain | 季风雨 | order | 6 | conditional | weather_variant_required | 纯名称不放行；须当前描述解析独立天气版本并再次复核。 |
| monsoon_rot | 季风侵袭 | order | 6 | eligible | direct | A#140 |
| monty | 蒙哥马利 | order | 1 | eligible | target | 需要目标#69 |
| mosquito_b_mk_iv | 蚊式 B Mk IV | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mosquito_f_mk_ii | 蚊式 F Mk II | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mosquito_fb_mk_vi | 蚊式 FB Mk VI | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| mother_russia | 俄罗斯母亲 | order | 4 | eligible | direct | A#94 |
| motherland_calls | 祖国在召唤！ | order | 3 | eligible | direct | B#117(未特别指定) |
| motti_tactic | 柴堆战术 | order | 8 | eligible | target | 需要目标#209 |
| mountain_offensive | 山地攻势 | order | 6 | eligible | direct | B#180(未特别指定) |
| mud | 泥泞 | order | 2 | eligible | direct | A#47 |
| murase_battalion | 村濑大队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| n1k1_kyofu | N1K1 强风一一型 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| n1kj_shiden | N1K-J 紫电局地战 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| nakajima_b5n2 | B5N2 九七舰攻 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| nara_regiment | 关岛守备队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| national_fire_service | 国家消防局 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| national_service | 国民服役 | order | 5 | eligible | direct | A#125 |
| naval_battle | 海战 | order | 7 | eligible | choice | 抉择#38 白名单:两个选项 / 选右边 |
| naval_bombardment | 海军轰炸 | order | 4 | eligible | target | B#143 用户指定 |
| naval_engagement | 海军交战 | order | 9 | eligible | direct | A#156 |
| naval_operation | 海军行动 | order | 3 | eligible | direct | A#78 |
| naval_power | 海军力量 | order | 1 | eligible | target | 需要目标#55 |
| naval_supply_run | 海上补给运输 | order | 3 | eligible | direct | B#115(未特别指定) |
| naval_support | 海军支援 | order | 2 | eligible | target | 需要目标#115 |
| naval_task_force | 海军特遣队 | order | 1 | disabled | unmarked_choice | 抉择#6:不在白名单里 |
| nebelwerfer_42 | 喷烟者 42 型 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| new_doctrine | 新式战法 | order | 1 | eligible | target | 需要目标#47 |
| night_attack | 夜间攻击 | order | 3 | eligible | target | B#106 用户指定 |
| night_bombing | 夜间轰炸 | order | 5 | eligible | target | 需要目标#196 |
| night_hunters | 暗夜猎手 | countermeasure | 4 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| night_patrol | 黑夜巡视 | order | 2 | disabled | hand_choice | 需要目标#141 |
| night_raid | 夜袭 | order | 4 | eligible | direct | B#132(未特别指定) |
| night_witches | 黑夜女巫 | order | 3 | eligible | direct | A#90 |
| no_10_commando | 第 10 突击队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| no_1_commando | 第 1 突击队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| no_3_commando | 第 3 突击队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| no_43_commando | 第 43 突击队 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| no_46_commando | 第 46 突击队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| no_9_commando | 第 9 突击队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| no_retreat | 背水一战 | order | 0 | eligible | target | 需要目标#15 |
| no_surrender | 决不投降 | order | 5 | eligible | direct | A#121 |
| nzans | 新西兰陆军护理队 | order | 3 | eligible | direct | B#112(未特别指定) |
| obice_da_7513 | 75/13 式山炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| observer_corps | 观察团 | order | 1 | disabled | blacklist | 需要目标#72 |
| old_hares | 老兔子 | order | 2 | disabled | blacklist | 需要目标#128 |
| on_the_ascent | 如日方升 | order | 3 | eligible | direct | A#75 |
| on_the_horizon | 海平面 | order | 1 | eligible | direct | A#30 |
| one_roof | 虚妄之梦 | order | 4 | eligible | direct | A#95 |
| order_227 | 第 227 号命令 | order | 2 | eligible | direct | A#57 |
| order_of_the_day | 动员令 | order | 3 | eligible | direct | B#102(未特别指定) |
| orders_from_above | 上级指令 | order | 2 | disabled | blacklist | 需要目标#82 |
| orp_byskawica | ORP 闪电号 | order | 3 | eligible | direct | B#96(未特别指定) |
| orp_general_haller | ORP 哈勒将军号 | order | 8 | eligible | target | B#195 用户指定 |
| orp_orze | ORP 鹰号 | order | 1 | eligible | direct | 需要目标#19 用户说「不是指向」-> 按不需要目标 |
| osaka_regiment | 大阪联队 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ot34 | OT-34 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| out_of_the_mist | 穿云破雾 | order | 1 | eligible | target | 需要目标#64 |
| out_of_the_sun | 逆光攻击 | order | 2 | eligible | direct | A#63 |
| out_with_the_old | 推陈出新 | order | 1 | disabled | blacklist | 需要目标#44 |
| outflank | 包抄 | order | 3 | disabled | blacklist | 需要目标#145 |
| outmaneuver | 以智取胜 | order | 1 | disabled | blacklist | 需要目标#23 |
| outrage | 激怒 | order | 2 | disabled | blacklist | 黑名单同族「激怒」:用户点名别带 |
| overcast | 阴云密布 | order | 2 | eligible | three | B#91 用户指定 |
| overpower | 摧枯拉朽 | order | 2 | disabled | blacklist | 需要目标#108 |
| overrun | 横扫千军 | order | 2 | eligible | direct | A#44 |
| overwhelming_force | 势不可挡 | order | 5 | disabled | hand_choice | 需要目标#195 两步:5 -> 1 |
| ox_and_bucks | 牛津郡和白金汉郡轻步兵团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| oxford | 牛津 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p1y1_model_11 | P1Y1 银河一一型 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p1y_ginga | P1Y 银河陆爆 | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p38d_lightning | P-38D 闪电 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p38h_lightning | P-38H 闪电 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p39_airacobra | P-39 飞蛇 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p40_k | P-40 K | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p40_kittyhawk | P-40 小鹰 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p40_n5 | P-40 N-5 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p40_warhawk | P-40 战鹰 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p40b_tomahawk | P-40B 战斧 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p47d25re | P-47D-25-RE | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p47d_thunderbolt | P-47D 雷电 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p51_b | P-51 B | fighter | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p51_mustang | P-51 野马 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| p61_black_widow | P-61 黑寡妇 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pact_of_steel | 钢铁条约 | order | 4 | eligible | direct | B#154(未特别指定) |
| pak_36 | Pak 36 反坦克炮 | artillery | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pak_36_fi | Pak 36 反坦克炮 FI | artillery | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pak_38 | Pak 38 反坦克炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pak_40 | Pak 40 反坦克炮 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pams | 警察辅助信使队 | order | 1 | unreviewed | unreviewed | 还没归类 |
| panther_a | 豹式坦克 A 型 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panther_a_zimmerit | 豹式坦克 A 型 防磁装甲型 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panther_d | 豹式坦克 D 型 | tank | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panther_g | 豹式坦克 G 型 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_35t | 35(t) 坦克 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_38t | 38(t) 坦克 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_i_dak | 一号坦克 DAK | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_ia | 一号坦克 A 型 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_ib | 一号坦克 B 型 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_ib_vet | 一号坦克 B 型 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iia | 二号坦克 A 型 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iic | 二号坦克 C 型 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iiie | 三号坦克 E 型 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iiif | 三号坦克 F 型 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iiig | 三号坦克 G 型 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iiih | 三号坦克 H 型 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iiij | 三号坦克 J 型 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iiij_late | 三号坦克 J 型 晚期型 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iiij_late_vet | 三号坦克 J 型 晚期型 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iiil | 三号坦克 L 型 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_iv_f2 | 四号坦克 F2 型 | tank | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_ivg | 四号坦克 G 型 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_ivh | 四号坦克 H 型 | tank | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_ivh_vet | 四号坦克 H 型 | tank | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzer_ivj | 四号坦克 J 型 | tank | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| panzerzug_61_bp42 | BP-42 装甲列车 | tank | 9 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| parachute_assault | 伞降突袭 | order | 4 | unreviewed | unreviewed | 还没归类 |
| parade | 阅兵 | order | 3 | eligible | direct | B#123(未特别指定) |
| partisans | 游击队 | order | 6 | eligible | target | B#184 用户指定 |
| partnership | 合作关系 | order | 6 | eligible | direct | B#178(未特别指定) |
| patriotic_firestorm | 爱国风暴 | order | 2 | eligible | direct | A#52 |
| patriotic_zeal | 爱国热忱 | order | 7 | eligible | direct | B#194(未特别指定) |
| patrol | 巡逻队 | order | 2 | eligible | target | 需要目标#99 |
| patton | 巴顿 | order | 1 | eligible | direct | A#21 |
| pb2y_coronado | PB2Y 科罗纳多 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pb4y2_privateer | PB4Y-2 私掠船 | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pby_catalina | PBY 卡特琳娜 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| penicillin | 青霉素 | order | 0 | eligible | direct | A#9 |
| persian_corridor | 波斯走廊 | order | 2 | disabled | blacklist | 需要目标#113 |
| petlyakov_pe2 | 佩-2 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| petlyakov_pe2ft | 佩-2 FT | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| phoney_war | 假战 | order | 5 | eligible | direct | A#120 |
| pilot_escape | 异乡之翼 | order | 2 | eligible | three | B#59 用户指定 |
| plan | 计划 | order | 2 | eligible | direct | B#81(未特别指定) |
| plan_d | 迪勒计划 | order | 3 | eligible | choice | 抉择#27 白名单:两个选项 / 选右边 |
| plan_west | 西线计划 | order | 3 | eligible | direct | A#85 |
| planned_attack | 预定攻势 | order | 2 | eligible | choice | 抉择#19 白名单:两个选项 / 选右边 |
| polikarpov_po2 | 波-2 | bomber | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| polikarpov_po2ii | 波-2-II | bomber | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pontoon_bridge | 浮桥 | order | 2 | eligible | target | 需要目标#114 |
| potez_63_11 | 波泰 63.11 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pound | 重击 | order | 1 | disabled | blacklist | 需要目标#76 |
| precision_bombing | 精准轰炸 | order | 7 | eligible | target | 需要目标#207 |
| pressurized_cabin | 加压舱 | order | 0 | eligible | direct | B#2(未特别指定) |
| production | 生产 | order | 0 | eligible | direct | B#5(未特别指定) |
| production_order | 生产令 | order | 1 | eligible | choice | 抉择#7 白名单:两个选项 / 选左边 |
| prolonged_siege | 长久围困 | order | 5 | eligible | direct | A#131 |
| promotion | 晋升 | order | 3 | eligible | direct | B#114(未特别指定) |
| propaganda | 战争宣传 | order | 1 | disabled | blacklist | B#20 用户指定:选择并弃一张反制 |
| protect_the_pocket | 困兽犹斗 | order | 10 | eligible | direct | A#158 |
| protected_convoy | 护送航运 | order | 1 | eligible | direct | B#23(未特别指定) |
| provence_landing | 普罗旺斯登陆 | order | 1 | eligible | direct | A#25 |
| pummel | 炮火连击 | order | 4 | eligible | target | B#144 用户指定 |
| punish | 严惩 | order | 2 | eligible | direct | B#46(未特别指定) |
| pursuit | 追击 | order | 4 | eligible | target | 需要目标#194 |
| push | 推进！ | order | 4 | eligible | target | 需要目标#178 |
| pz_befehlswagen_35t | 35(t) 指挥车 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pzl_23_karas | PZL.23 卡拉斯 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pzl_37_o | PZL.37 麋鹿 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pzl_p_11 | PZL P.11 | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| pzl_p_7 | PZL P.7 | fighter | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| qf_40mm_mk_iii | 40 毫米高射炮  Mk III | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| queens_own | 女王直属卡梅伦高地人团 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| quinine | 奎宁 | order | 1 | disabled | blacklist | 需要目标#37 |
| raaf_hurricane_trop | RAAF 飓风 热带型 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| raaf_lightning_f4 | RAAF 闪电 F-4 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| raaf_walrus | RAAF 海象 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| raaf_walrus_vet | RAAF 海象 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| radar | 雷达 | order | 0 | eligible | direct | B#7(未特别指定) |
| radar_alert | 雷达警报 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| raf_buffalo_mk_i | RAF 水牛 Mk I | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| raf_ground_crew | 皇家空军地勤 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| raf_mitchell | RAF 米切尔 | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| raf_mustang | RAF 野马 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| raid | 奇袭 | order | 1 | eligible | direct | A#18 |
| rally | 重整旗鼓 | order | 2 | eligible | direct | B#88(未特别指定) |
| rally_caledonia | 喀里多尼亚归附 | order | 2 | unreviewed | unreviewed | 还没归类 |
| rapid_engagement | 迅速交战 | order | 3 | eligible | target | B#122 用户指定 |
| rapid_response | 迅速响应 | order | 2 | eligible | direct | B#86(未特别指定) |
| rasputitsa | 泥泞季 | order | 2 | unreviewed | unreviewed | 还没归类 |
| rationing | 配给制 | order | 2 | eligible | choice | 抉择#18 白名单:两个选项 / 选右边 |
| reckless_assault | 鲁莽攻击 | order | 2 | eligible | direct | A#66 |
| recuperation | 休养 | order | 2 | eligible | target | 需要目标#87 |
| red_banner | 红色旗帜 | order | 2 | eligible | target | 需要目标#126 |
| red_bull | 红牛师 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| red_dawn | 赤色黎明 | order | 1 | disabled | unmarked_choice | 抉择#12:不在白名单里 |
| red_devils | 红魔空降步兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| red_october | 红色十月 | order | 4 | disabled | blacklist | 需要目标#188 |
| redeployment | 重新部署 | order | 4 | eligible | direct | A#113 |
| refit | 整修 | order | 1 | disabled | unmarked_choice | 抉择#5:不在白名单里 |
| regia_aeronautica | 意大利皇家空军 | order | 5 | eligible | direct | B#165(未特别指定) |
| regia_marina | 意大利皇家海军 | order | 2 | eligible | direct | A#40 |
| reich_research | 德意志帝国研发 | order | 3 | eligible | choice | 抉择#21 白名单:两个选项 / 选右边 |
| reichsbank | 德意志帝国银行 | order | 3 | eligible | direct | A#76 |
| reinforcements | 增援 | order | 3 | eligible | direct | B#105(未特别指定) |
| reorganize | 调整 | order | 0 | disabled | hand_choice | 需要目标#16 |
| repel_the_attack | 击退进攻 | order | 4 | unreviewed | unreviewed | 还没归类 需最右手牌位置和提前结束回合风险判断。 |
| rescue_mission | 营救任务 | countermeasure | 4 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| reserves | 预备役 | order | 1 | eligible | direct | B#44(未特别指定) |
| resistance_b | 抵抗 | order | 0 | unreviewed | ignored | 需要目标#9 用户说「不用管」 |
| resistance_council | 全国抵抗委员会 | order | 1 | eligible | target | 需要目标#27 |
| resolute_defense | 坚决守护 | order | 1 | disabled | blacklist | 需要目标#34 |
| resourcefulness | 足智多谋 | order | 1 | eligible | direct | B#37(未特别指定) |
| respite | 喘息之机 | order | 4 | eligible | direct | A#100 |
| retaliation | 复仇 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| retribution | 惩戒 | order | 2 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_b | 惩戒 | order | 0 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_c | 惩戒 | order | 3 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_d | 惩戒 | order | 2 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_e | 惩戒 | order | 2 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_f | 惩戒 | order | 3 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_g | 惩戒 | order | 6 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_h | 惩戒 | order | 5 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_i | 惩戒 | order | 12 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_j | 惩戒 | order | 2 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_k | 惩戒 | order | 1 | disabled | blacklist | 黑名单同族「惩戒」:用户点名别带 |
| retribution_l | 惩戒 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| ride_of_the_valkyries | 女武神的骑行 | order | 2 | eligible | direct | A#38 |
| rm_bersagliere | RM 神射手号 | order | 1 | eligible | direct | B#8(未特别指定) |
| rm_roma | RM 罗马号 | order | 4 | eligible | target | 需要目标#170 |
| rnzaf_kittyhawk | RNZAF 小鹰 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| road_to_berlin | 柏林之路 | order | 1 | eligible | direct | A#27 |
| romanian_bridgehead | 罗马尼亚桥头堡 | order | 2 | eligible | target | 需要目标#127 |
| root_out_the_enemy | 斩草除根 | order | 4 | eligible | direct | A#104 |
| rout | 溃敌 | order | 1 | eligible | target | B#29 用户指定 |
| routed_troops | 溃军 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| royal_fusiliers | 皇家燧发枪兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| royal_research | 皇家研发 | order | 3 | eligible | choice | 抉择#23 白名单:两个选项 / 选左边 |
| royal_scots | 皇家苏格兰团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| royal_sussex_regiment | 皇家萨塞克斯团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| royal_ulster_rifles | 皇家阿尔斯特步枪兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| royal_west_kents | 皇家西肯特郡团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| ruffians | 恶汉团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| rule_britannia | 统治吧！不列颠尼亚！ | order | 8 | eligible | direct | A#153 |
| rule_the_skies | 统治天空 | order | 2 | eligible | direct | A#58 |
| run_the_battlefield | 掌控战场 | order | 4 | eligible | direct | B#139(未特别指定) |
| rush | 强袭 | order | 1 | eligible | target | 需要目标#40 |
| rush_production | 加急生产 | order | 1 | eligible | direct | A#13 |
| ryhm_susi | 苏西战斗群 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| saar_offensive | 萨尔攻势 | order | 6 | eligible | target | 需要目标#203 |
| sabae_regiment | 鲭江联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sabotage | 毁坏 | order | 7 | eligible | three | 需要目标#206 |
| sakura_regiment | 佐仓联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| salamander | He 162 蝾螈 | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sally | 出动 | order | 0 | disabled | blacklist | 需要目标#5 |
| salpa_line | 萨尔帕防线 | order | 2 | eligible | direct | B#78(未特别指定) |
| sapporo_regiment | 札幌联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| savoia_cavalleria | 萨沃亚骑兵团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| savoiamarchetti_sm_79 | 萨沃亚-马尔凯蒂 SM.79 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sb2c_helldiver | SB2C 地狱俯冲者 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sbd_3_dauntless | SBD 3 无畏 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| scatter_tactics | 分散战术 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| scorched_earth | 焦土政策 | order | 2 | eligible | direct | A#51 |
| scorching_sun | 骄阳 | order | 6 | conditional | weather_variant_required | 纯名称不放行；须当前描述解析独立天气版本并再次复核。 |
| scouting_party | 侦察队 | order | 3 | eligible | direct | A#72 |
| scrap_metal | 金属废料 | order | 1 | disabled | hand_choice | B#40 用户指定 |
| screening_force | 掩护部队 | order | 7 | eligible | direct | B#192(未特别指定) |
| sd_kfz_10_pak_38 | Sd Kfz 10 PaK 38 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sd_kfz_222 | Sd KFz 222 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sd_kfz_2509 | Sd Kfz 250/9 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sdf | 苏丹防卫军 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sea_embargo | 海运禁令 | order | 2 | eligible | target | 需要目标#117 |
| sea_patrol | 海上巡逻 | order | 4 | eligible | target | 需要目标#181 |
| seabees | 海蜂队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| seaborne_invasion | 海上入侵 | order | 8 | eligible | direct | A#152 |
| seac | 东南亚司令部 | order | 3 | eligible | direct | B#98(未特别指定) |
| seaforth_highlanders | 锡福斯高地人团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| seagull | SO3C 海鸥 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| seahawk | SC 海鹰 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| second_chance | 第二次机会 | order | 4 | eligible | direct | A#110 |
| second_front | 第二战线 | order | 4 | disabled | blacklist | B#150 用户指定 |
| secret_operatives | 秘密特工 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| section_ii | 总参二局 | order | 2 | eligible | direct | B#61(未特别指定) |
| seek_and_destroy | 穷追猛打 | order | 4 | eligible | direct | B#148(未特别指定) |
| semovente_da_7518 | 75/18 式自走炮 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| semper_fi | 永远忠诚 | order | 1 | eligible | direct | A#29 |
| sendai_regiment | 仙台联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sexton | 司事火炮 | artillery | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| shadow_strike | 暗影袭击 | order | 1 | eligible | target | 需要目标#48 |
| shark_mk_iii | 鲨鱼 Mk III | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| shelling | 炮击 | order | 5 | eligible | direct | B#170(未特别指定) |
| sherwood_foresters | 舍伍德森林人团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| shibata_regiment | 新发田联队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| shifting_attack | 转变攻击 | order | 2 | eligible | target | B#83 用户指定 |
| shifting_doctrine | 转变战法 | order | 1 | eligible | direct | B#39(未特别指定) |
| shinyo_motorboats | 震洋特攻摩托艇 | order | 1 | eligible | target | 需要目标#78 |
| shock_attack | 震慑冲击 | order | 2 | eligible | direct | A#65 |
| shock_tactics | 突击战术 | order | 2 | disabled | unmarked_choice | 抉择#16:不在白名单里 |
| shoge_detachment | 庄下支队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| shore_bombardment | 对岸轰炸 | order | 4 | disabled | unmarked_choice | 抉择#30:不在白名单里 |
| shturmovik_il2m | 伊尔-2M | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| siberian_transfer | 西伯利亚转移 | order | 2 | eligible | direct | B#80(未特别指定) |
| sincerely_yours | 诚挚问候 | order | 4 | eligible | direct | A#111 |
| sissi | 游击队员 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sissiosasto_5_d | 第 5 师独立游击支队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sisu | 西苏精神 | countermeasure | 3 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| ski_troops | 滑雪部队 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| sky_barons | 空中男爵 | order | 4 | disabled | blacklist | 需要目标#186 |
| slashers | 砍杀者团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sloped_armor | 倾斜装甲 | order | 0 | eligible | target | 需要目标#4 |
| sneak_attack | 潜行突击 | order | 8 | eligible | target | 需要目标#210 |
| sneak_maneuver | 潜伏特训 | order | 1 | disabled | blacklist | 需要目标#56 |
| sniped | 阻击 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| snowstorm | 暴风雪 | order | 1 | eligible | direct | A#26 |
| somua_s35 | 索玛 S35 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sortie | 出击 | order | 1 | disabled | unmarked_choice | 抉择#3:不在白名单里 |
| soul_of_old_japan | 苇原之魂 | order | 2 | eligible | three | 需要目标#96 |
| southern_plan | 南进计划 | order | 4 | eligible | direct | B#129(未特别指定) |
| soviet_military_research | 苏联军事研发 | order | 3 | eligible | choice | 抉择#26 白名单:两个选项 / 选右边 |
| spars | 妇女预备队 | order | 1 | eligible | choice | 抉择#4 白名单:两个选项 / 选左边 |
| spearhead | 先锋 | order | 2 | eligible | target | 需要目标#89 |
| special_assignment | 特别任务 | order | 6 | disabled | hand_choice | B#185 用户指定 |
| special_attack | 特攻 | order | 3 | eligible | direct | B#72(未特别指定) |
| special_delivery | 特快专递 | order | 2 | eligible | direct | A#53 |
| special_reinforcements | 特殊增援 | order | 2 | eligible | direct | B#73(未特别指定) |
| spirit_of_rome | 罗马精神 | order | 5 | eligible | target | 需要目标#199 |
| spitfire_mk_ia | 喷火 Mk Ia | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| spitfire_mk_ii | 喷火 Mk II | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| spitfire_mk_iia | 喷火 Mk IIa | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| spitfire_mk_v | 喷火 Mk V | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| spitfire_mk_v_pl | 喷火 Mk V PL | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| spoils_of_war | 战利品 | order | 2 | eligible | three | 需要目标#105 |
| spring_offensive | 春季攻势 | order | 4 | eligible | direct | B#141(未特别指定) |
| spy_ring | 间谍组织 | order | 2 | eligible | direct | B#90(未特别指定) |
| stalins_organ | 斯大林管风琴 | order | 4 | eligible | direct | B#140(未特别指定) |
| stand_fast | 坚守不退 | order | 3 | disabled | blacklist | 需要目标#148 |
| stand_together | 同仇敌忾 | order | 1 | eligible | target | 需要目标#30 |
| standard_ammo | 标准弹药 | order | 0 | eligible | direct | A#4 |
| stars_stripes | 星条旗 | order | 5 | eligible | direct | A#128 |
| stealth_mission | 潜行任务 | order | 3 | eligible | target | 需要目标#157 |
| stiff_upper_lip | 咬紧牙关 | order | 2 | eligible | direct | B#55(未特别指定) |
| stirling_mk_i_s3 | 斯特林 Mk I S3 | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| stirling_mk_iii | 斯特林 Mk III | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| storm_division | 岚兵团 | infantry | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| strafing | 低空扫射 | order | 1 | disabled | unmarked_choice | 抉择#1:不在白名单里 |
| stranglehold | 截断 | countermeasure | 1 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| strategic_bombing | 战略轰炸 | order | 6 | eligible | direct | B#181(未特别指定) |
| strategic_focus | 战略重心 | order | 7 | eligible | choice | 抉择#37 白名单:两个选项 / 选左边 |
| strategic_planning | 战略规划 | order | 10 | eligible | direct | A#161 |
| stretch_the_line | 延长战线 | order | 2 | eligible | direct | B#58(未特别指定) |
| strike_from_the_woods | 林间袭击 | order | 1 | eligible | target | 需要目标#52 |
| strike_group | 航母打击群 | order | 3 | eligible | direct | B#120(未特别指定) |
| strong_bond | 戮力同心 | order | 4 | eligible | target | 需要目标#177 |
| stubborn_defense | 殊死防守 | countermeasure | 0 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| stug_iii_g_schrzen | 三号突击炮 G 型 裙甲型 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| stug_iiif | 三号突击炮 F 型 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| stug_iiig | 三号突击炮 G 型 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| stug_iv | 四号突击炮 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| stuka_87g | Ju 87 G 斯图卡 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| stuka_87g_vet | Ju 87 G 斯图卡 | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sturmbrigade_rhodos | 罗得突击旅 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sturmi | 三号突击炮 FI | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| stz5_katyusha | STZ-5 喀秋莎 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| su100 | SU-100 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| su76m | SU-76M | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| su85 | SU-85 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| su_152 | SU-152 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sudden_strike | 突然袭击 | order | 2 | disabled | blacklist | 需要目标#124 |
| sunderland_mk_v | 桑德兰 Mk V | bomber | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sunrise_division | 旭兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| supply_chain | 供应链 | order | 2 | eligible | direct | B#49(未特别指定) |
| supply_drop | 空投补给 | order | 2 | disabled | blacklist | 需要目标#123 |
| supply_front | 前线补给 | order | 5 | eligible | direct | A#122 |
| supply_priorities | 补给优先 | order | 1 | eligible | choice | 抉择#10 白名单:两个选项 / 选左边 |
| supply_shipment | 运输补给 | order | 2 | eligible | target | B#87 用户指定 |
| supply_shortage | 物资短缺 | order | 3 | eligible | direct | A#81 |
| support_column | 支援纵队 | order | 1 | eligible | target | 需要目标#45 |
| suppression | 抑制 | order | 1 | eligible | target | B#22 用户指定 |
| surazh_gate | 苏拉日之门 | order | 2 | eligible | target | 需要目标#130 |
| surging_power | 澎湃力量 | order | 4 | eligible | direct | A#107 |
| surprise_attack | 偷袭 | order | 1 | eligible | target | 需要目标#25 |
| surprise_engagement | 突发交战 | order | 5 | eligible | direct | B#173(未特别指定) |
| surveil | 监视 | order | 1 | disabled | blacklist | 需要目标#60 |
| sustained_pressure | 持续施压 | order | 1 | eligible | target | 需要目标#43 |
| swift_response | 快速响应 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| swift_victory | 快速胜利 | order | 1 | eligible | target | A#23 L168 用户指定:对一个目标造成伤害 |
| swordfish_mk_i | 剑鱼 Mk I | bomber | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| sykes_regulars | 赛克斯正规军 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| synthetic_oil | 合成机油 | order | 0 | eligible | direct | B#3(未特别指定) |
| synthetic_rubber | 合成橡胶 | order | 0 | eligible | target | 需要目标#6 |
| t19_howitzer | T19 榴弹炮 | artillery | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t26_fi | T-26 FI | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t28 | T-28 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t3476d | T-34-76D | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t3485 | T-34-85 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t3485_1944 | T-34-85 1944 | tank | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t3485_1945 | T-34-85 1945 | tank | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t34_1942 | T-34 1942 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t34_1942_b | T-34 1942 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t34_76_pl | T-34-76 PL | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t35 | T-35 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t60 | T-60 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t70 | T-70 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t70_b | T-70 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| t80 | T-80 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tactical_retreat | 暂避锋芒 | order | 1 | unreviewed | unreviewed | 限定目标尚未实现:仅花费不大于4的友方德国单位 需当前友方德国单位及不大于4费的限定目标验证。 |
| tactical_strike | 战术打击 | order | 3 | eligible | target | 需要目标#151 |
| tactical_withdrawal | 战术撤退 | order | 1 | eligible | target | B#21 用户指定 |
| takasaki_regiment | 高崎联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| take_initiative | 先发制人 | order | 2 | eligible | direct | B#50(未特别指定) |
| take_liberty | 池鱼笼鸟 | order | 4 | eligible | direct | A#106 |
| tamanskaya | 塔曼斯卡亚！ | order | 1 | eligible | direct | A#16 |
| tank_maneuver | 坦克机动 | order | 2 | disabled | blacklist | 需要目标#95 |
| tank_wedge | 装甲楔形阵 | order | 1 | unreviewed | unreviewed | 判为需要目标,但还没给它规格 需当前友方德国坦克及邻接单位信息。 |
| target_acquired | 目标锁定 | order | 1 | disabled | blacklist | 需要目标#61 |
| task_force_44 | 第 44 特混舰队 | order | 2 | unreviewed | follow | 需要目标#125 两步:7 -> 1 |
| tbf1_avenger | TBF-1 复仇者 | bomber | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tempest_mk_v | 暴风 Mk V | fighter | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_alliance | 同盟国 | order | 5 | eligible | direct | A#124 |
| the_american_guard | 美国人卫队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_anzac_spirit | 澳新军团精神 | order | 8 | eligible | direct | B#196(未特别指定) |
| the_big_three | 三巨头 | order | 5 | eligible | direct | B#159(未特别指定) |
| the_biscuit_boys | 饼干男孩步兵团 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_bleeders | 流血者团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_commonwealth | 英联邦 | order | 12 | disabled | blacklist | 需要目标#215 |
| the_dagger_strikes | 单刀直入 | order | 3 | eligible | target | 需要目标#146 |
| the_desert_rats | 沙漠之鼠 | order | 1 | eligible | target | 需要目标#54 |
| the_deuce | 杜斯团 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_double_sunrise | 双日出航线 | order | 2 | eligible | direct | B#53(未特别指定) |
| the_empire_strikes | 帝国进击 | order | 4 | eligible | direct | B#135(未特别指定) |
| the_glamour_boys | 魅力男孩高地人团 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_great_expanse | 阔土 | order | 4 | eligible | direct | B#155(未特别指定) |
| the_hammer | 铁锤 | order | 3 | eligible | target | 需要目标#167 |
| the_holy_boys | 神圣男孩步兵团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_land_girls | 土地女孩 | order | 2 | eligible | direct | A#36 |
| the_merchant_navy | 商船队 | countermeasure | 2 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| the_mighty_fall | 巨人陨落 | order | 3 | disabled | blacklist | 需要目标#149 |
| the_peoples_army | 人民军 | order | 6 | eligible | direct | A#136 |
| the_polar_bears | 北极熊师 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_pompadours | 蓬帕杜团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_professionals | 专家步兵团 | infantry | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_rangers | 游骑兵营 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_regulars | 正规军装甲步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_regulars_vet | 正规军装甲步兵团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_rock_of_gibraltar | 直布罗陀巨岩 | order | 4 | unreviewed | unreviewed | 还没归类 需连续开发选牌流程及策略验证。 |
| the_silent_seventh | 沉默七师 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_silent_seventh_vet | 沉默七师 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_tide_turns | 潮起潮落 | order | 3 | eligible | direct | A#79 |
| the_tigers | 老虎团 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| the_war_machine | 战争机器 | order | 2 | eligible | direct | B#62(未特别指定) |
| the_white_death | 白色死神 | order | 4 | eligible | direct | B#147(未特别指定) |
| through_the_breach | 乘虚而入 | order | 1 | eligible | target | 需要目标#22 |
| through_the_ice | 步履薄冰 | order | 2 | eligible | target | 需要目标#112 |
| thunder_division | 雷兵团 | infantry | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| thunderbolt | 霹雳师 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| thunderstorm | 雷暴 | order | 2 | conditional | weather_variant_required | 纯名称不放行；须当前描述解析独立天气版本并再次复核。 |
| tiger_ie | 虎式坦克 E 型 | tank | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tiger_ih | 虎式坦克 H 型 | tank | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tiger_moth | 虎蛾 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tigercat | F7F 虎猫 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| timely_supplies | 及时补给 | order | 2 | eligible | direct | B#52(未特别指定) |
| tip_of_the_spear | 矛尖 | order | 4 | disabled | blacklist | 需要目标#185 |
| tks | TKS | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| to_the_last_man | 至死方休 | order | 10 | eligible | direct | A#162 |
| tora_tora_tora | 虎！虎！虎！ | order | 2 | eligible | direct | B#79(未特别指定) |
| torpedo_attack | 鱼雷攻击 | order | 3 | eligible | target | B#125 用户指定 |
| torrential_rain | 骤雨 | order | 4 | conditional | weather_variant_required | 纯名称不放行；须当前描述解析独立天气版本并再次复核。 |
| tottori_regiment | 鸟取联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| toyama_regiment | 富山联队 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tractor_factories | 拖拉机厂 | order | 8 | eligible | direct | A#150 |
| trento_division | 特伦托师 | infantry | 8 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tropic_lightning | 热带闪电师 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tropic_lightning_vet | 热带闪电师 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tropical_storm | 热带风暴 | order | 4 | conditional | weather_variant_required | 纯名称不放行；须当前描述解析独立天气版本并再次复核。 |
| tsu_regiment | 津联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tsuruga_regiment | 敦贺联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tupolev_sb2 | 斯勃-2 | bomber | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tupolev_tb3 | 特勃-3 | bomber | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| tupolev_tu2 | 图-2 | bomber | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| turmoil | 动乱 | order | 2 | eligible | target | 需要目标#91 |
| turning_point | 转折点 | order | 2 | eligible | direct | A#62 |
| type_1_37mm | 一式反坦克炮 | artillery | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_1_chihe | 一式中战车 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_3_chinu | 三式中战车 | tank | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_4_chito | 四式中战车 | tank | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_4_horo | 四式自走炮 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_88_aa_gun | 八八式高射炮 | artillery | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_89_chiro | 八九式中战车 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_92_105mm_field_gun | 九二式野战炮 | artillery | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_92_jyushokosha | 九二式重装甲车 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_93 | 九三式装甲车 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_94_tk | 九四式轻装甲车 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_94_tk_early | 九四式轻装甲车早期型 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_95_hago | 九五式轻战车 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_96_aa_gun | 九六式高射炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_97_chiha | 九七式中战车 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_97_shinhoto | 九七式改中战车 | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_98_keni | 九八式轻战车 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| type_xxi_uboat | XXI 级 U 型潜艇 | order | 0 | eligible | target | 需要目标#3 |
| typhoon_mk_ib | 台风 Mk Ib | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| u16 | U-16 | order | 2 | eligible | target | 需要目标#80 |
| u375 | U-375 | order | 2 | eligible | direct | B#45(未特别指定) |
| u48 | U-48 | order | 3 | eligible | direct | A#69 |
| ultra | ULTRA | countermeasure | 3 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| uncle_sam | 山姆大叔 | order | 4 | eligible | direct | B#133(未特别指定) |
| under_fire | 枪林弹雨 | order | 3 | eligible | target | 需要目标#154 |
| underground_state | 地下国 | order | 4 | eligible | target | 需要目标#174 |
| unexpected_resistance | 意外反抗 | countermeasure | 0 | disabled | counter_unimplemented | 反制没有自动响应时机路径。 |
| united_we_stand | 团结则存 | order | 1 | eligible | target | 需要目标#32 |
| unity_is_strength | 团结就是力量 | order | 2 | eligible | target | 需要目标#94 |
| universal_carrier | 通用载具 | tank | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| upgrade | 改装 | order | 2 | disabled | blacklist | 需要目标#109 |
| uprising | 起义 | order | 5 | eligible | direct | A#130 |
| ura | 呜啦！ | order | 3 | eligible | direct | A#74 |
| ural_factories | 乌拉尔工厂 | order | 2 | eligible | target | 需要目标#86 |
| uranprojekt | 铀工程 | order | 12 | eligible | target | 需要目标#216 |
| urban_fighting | 巷战 | order | 4 | eligible | target | 需要目标#176 |
| us_military_research | 美国军事研发 | order | 3 | eligible | choice | 抉择#25 白名单:两个选项 / 选右边 |
| us_weather_bureau | 美国气象局 | order | 2 | eligible | choice | 抉择#17 白名单:两个选项 / 选左边 |
| usaaf | 美国陆军航空队 | order | 2 | unreviewed | unreviewed | 无需手动目标的抽牌候选；需卡组中美国飞机的可抽信息及手牌容量，尚未放行。 |
| usaaf_spitfire_ix | USAAF 喷火 IX | fighter | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| usace | 陆军工程兵团 | order | 0 | disabled | blacklist | 需要目标#17 |
| uss_archerfish | USS 射水鱼号 | order | 5 | eligible | direct | B#158(未特别指定) |
| uss_fitch | USS 菲奇号 | order | 3 | eligible | direct | A#70 |
| uss_missouri | USS 密苏里号 | order | 3 | eligible | target | B#97 用户指定 |
| uss_the_sullivans | USS 沙利文兄弟号 | order | 2 | eligible | target | 需要目标#81 |
| uss_yorktown | USS 约克城号 | order | 5 | eligible | direct | A#116 |
| utsunomiya_regiment | 宇都宫联队 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| uusimaa_regiment | 新地团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| v1_flying_bomb | V-1 飞行炸弹 | order | 0 | disabled | blacklist | 需要目标#2 |
| valentine_mk_ii | 瓦伦丁 Mk II | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| valentine_mk_iii | 瓦伦丁 Mk III | tank | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| vanguard | 先峰 | order | 2 | disabled | blacklist | 需要目标#88 |
| veteran_pilots | 资深飞行员 | order | 1 | disabled | unmarked_choice | 抉择#11:不在白名单里 |
| vicious_salvo | 激烈齐射 | order | 3 | eligible | target | 需要目标#158 |
| victory_banners | 胜利旗帜 | order | 7 | disabled | blacklist | 需要目标#208 |
| victory_garden | 胜利花园 | order | 3 | eligible | direct | A#83 |
| victory_march | 胜利进军 | order | 5 | eligible | direct | A#129 |
| vildebeest | 牛羚 | bomber | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| vive_la_resistance | 抵抗万岁！ | order | 2 | eligible | direct | B#63(未特别指定) |
| volunteer_corps | 国民义勇队 | order | 1 | eligible | target | B#12 用户指定 |
| vystrel_course | 高级步兵战术进修 | order | 2 | disabled | blacklist | 需要目标#140 |
| wakamatsu_regiment | 马坦尼考守备队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| war_bonds | 战争债券 | order | 5 | eligible | direct | B#167(未特别指定) |
| war_production | 战时生产 | order | 0 | eligible | direct | A#3 |
| wave_after_wave | 高潮迭起 | order | 6 | eligible | direct | A#144 |
| way_of_subjects | 臣民之道 | order | 2 | eligible | direct | A#59 |
| we_can_do_it | 我们能做到！ | order | 5 | eligible | direct | B#166(未特别指定) |
| welch_regiment | 威尔奇团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| wellington | 威灵顿 | bomber | 7 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| welsh_guards | 威尔士卫队 | infantry | 1 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| wespe | 黄蜂式自行火炮 | artillery | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| western_allies | 西方盟友 | order | 6 | eligible | direct | B#186(未特别指定) |
| whirlwind | 旋风 | fighter | 6 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| white_guard | 白卫队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| windhund_division | 灰猎犬师 | infantry | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| winter_offensive | 冬季攻势 | order | 7 | eligible | direct | B#188(未特别指定) |
| winter_regiment | 冬联队 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| winter_warfare | 冬季战争 | order | 1 | eligible | direct | B#10(未特别指定) |
| wirbelwind | 旋风防空坦克 | tank | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| wolfhounds | 猎狼犬团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| wolfhounds_vet | 猎狼犬团 | infantry | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| wolfpack | 狼群战术 | order | 4 | eligible | target | B#146 用户指定 |
| wolves_of_tuscany | 托斯卡纳之狼步兵师 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| women_at_work | 半边天 | order | 2 | disabled | blacklist | B#51 用户指定:仅美国单位 |
| workers_unite | 无产者，联合起来！ | order | 2 | eligible | direct | B#66(未特别指定) |
| yak_3 | 雅克-3 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| yak_7 | 雅克-7 | fighter | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| yak_9 | 雅克-9 | fighter | 5 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| yak_9_pl | 雅克-9 PL | fighter | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| yamagata_regiment | 山形联队 | infantry | 2 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| yank | 洋基周刊 | order | 7 | eligible | direct | B#193(未特别指定) |
| yokosuka_e14y | E14Y 零式小型水侦 | fighter | 3 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| your_courage | 你的勇气 | order | 3 | eligible | direct | A#71 |
| z_special_unit | Z 队 | order | 3 | eligible | target | 需要目标#142 |
| zamo_uprising | 扎莫希奇起义 | order | 2 | eligible | target | 需要目标#106 |
| zaza_division | 扎扎师 | infantry | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |
| zhukov | 朱可夫 | order | 1 | eligible | direct | B#25(未特别指定) |
| zis2 | ZiS-2 | artillery | 4 | eligible | unit_deploy | 通用单位部署路径；费用、槽位、身份等仍由当前帧检查。 |

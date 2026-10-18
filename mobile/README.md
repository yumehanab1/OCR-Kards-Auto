# 手机端 / Android 0.2.3

手机版独立维护，PC 发布包不包含 APK。[源码与构建说明](source/README.md)。

当前正式构建为 **0.2.3 / versionCode 151**，在原版基础上修复 Android 15 浮窗同步及输入准备超时边界。构建、签名、覆盖安装、12组设备发布检查、78项截图专项及浮窗状态组已通过；详见[发布报告](../docs/reports/mobile/APK_0.2.3_RELEASE.md)和[本次增量说明](releases/0.2.3-android15-window-sync.md)。

**同名 APK 已替换为 code151，可覆盖更新。** GitHub asset `652867560`；固定下载链接已匿名 HTTP200 回读 159,539,562 bytes，全部字节和 SHA-256 `9c8dfae65c3b60e8ec652863a4514f11f034d23ea87520423e90d291c4263cb7` 与本地及已安装正式包一致。原 PC 正文、两个 PC 附件及共享标签保持不变。

## 下载与使用

- [KARDS-AUTO-Mobile-v0.2.3.apk](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.3/KARDS-AUTO-Mobile-v0.2.3.apk)位于同页 [v0.2.3 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.3)。下载后覆盖安装，无需解压；核对版本号和SHA-256见发布报告。
- 最低 Android 11/API30，支持 arm64-v8a 和 x86_64。覆盖更新需要与已有安装使用相同签名；本次正式包沿用既有证书。
- 已内置 Python、NumPy/OpenCV、OCR 运行库和模型；运行无需 Windows、ADB、Termux、Shizuku 或另装 Python。
- 安装并登录 KARDS，在系统无障碍设置启用“KARDS 对战助手”。使用简体中文；**画质不限，内容比例设为“原生”，UI 比例调为 1**。
- Android 14 及以上使用游戏窗口截图。Android 11—13 若系统截图黑屏，可在助手主界面启用“兼容截图”，亲自在系统屏幕共享弹窗确认后返回游戏。进程重启或授权撤销后需要重新授权；部分 MuMu 环境还需处理助手虚拟屏旋转，适用范围见发布报告。
- 选择休闲/排位及局数，`0` 表示无限。可从菜单开始或接管当前对局。右侧悬浮条点击展开，展开继续运行，手动点击停止；输入期间面板会临时隐藏。
- 每步按攻击、移动、部署的顺序选择。新截图证据按 350MiB 预算管理，优先淘汰最旧非活动局；活动帧仍需暂存空间，旧版本历史不会自动迁移清理。

## 本次新增

- 浮窗隐藏时保留窗口附着，使用窗口及根 View 透明度和不可触控标记，减少窗口反复重建；嵌套隐藏及重复释放按同一租约处理。
- Android 14 及以上采集游戏窗口原生像素时，不再每帧隐藏浮窗；前台、遮挡及几何验证保留。
- 战斗、菜单和结算共用原子派发边界。准备阶段先超时的任务不能迟到提交输入；已提交输入的超时仍保守停止，不自动重发。新增有界阶段日志帮助定位等待环节。
- 沿用此前兼容截图、黑帧/透明帧拒绝和有限新鲜重采；8秒上限、前台、新鲜度、取消、预算、真实回执和动作后验条件保持，Guard关闭。

code150 开发包在 Android 15/API35、1280×720 的同一会话连续完成3局并结算回页，3负，用时23分0.602秒；110次战斗触控全部完成，4次短暂拒帧均一次重采恢复。code151 与其546个 main 文件的集合及字节一致，Gradle仅改版本号和名称；code151 是独立正式构建，没有新增该哈希完整对局，不能把 code150 三局记作 code151 同包实战。

此前 code147 开发包在 API32 MuMu 同一会话连续完成十局，2胜8负，用时1小时8分46.633秒；21次已记录缺图均一次重采恢复。该十局和原 code148 正式验证保留在[发布报告的历史记录](../docs/reports/mobile/APK_0.2.3_RELEASE.md)。

当前识别结合文字、模板、颜色和几何信息，其他设备及布局仍需实测。部分出牌后再选战场目标的流程尚未完整支持；普通效果未知和结束未确认的原记录均保留。连续完成不表示每个动作效果均已验证，也不证明胜率提升。旧 Android 11—13 兼容投影重启后的旋转修正尚未内置，OBS底层黑屏、实体手机及跨重启长时稳定性仍未验收。

## 历史版本

- [0.2.2 APK 直链](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.2/KARDS-AUTO-Mobile-v0.2.2.apk)及[0.2.2 验证报告/SHA-256](../docs/reports/mobile/APK_0.2.2_RELEASE.md)。
- [0.2.1 APK 直链](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.1/KARDS-AUTO-Mobile-v0.2.1.apk)及[0.2.1 验证报告/SHA-256](../docs/reports/mobile/APK_0.2.1_RELEASE.md)。
- 0.2.0 ZIP 与清单保留在[历史 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.0)。

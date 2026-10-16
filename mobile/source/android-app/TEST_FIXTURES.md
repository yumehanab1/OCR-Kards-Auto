# AndroidTest 回放素材

私有实机截图不随公开源码提供。正式 APK 的构建不依赖这些测试素材；运行 `releaseSmokeOnly` 的 12 组检查前，需要在本地准备素材。缺失素材表示测试尚未执行通过，不能跳过断言或改记成功。

测试资产可放在 `app/src/androidTest/assets/` 或 `app/build/generated/deviceTestAssets/` 下，同一路径只能提供一份。`clean` 会删除后一个目录，因此清理构建后需要重新准备其中的素材。

生命周期检查需要 `replay/game_opening.png`：自行提供一张 1280×720 或 1920×1080 的原始 PNG，画面必须是游戏内对局。该检查会验证真实回放结果为 `IN_GAME`、取消文件选择、无效 PNG、恢复回放及 Activity 重建；预检只检查文件格式和尺寸，不能代替设备断言。`replay/manifest.json` 及其六张回放图属于完整 `saved_frame_replay` 检查，不是本次 12 组检查的依赖。

其他依赖由各 AndroidTest 源码声明，预检会检查这些路径及清单哈希：

- `native-pipeline-probe/manifest.json` 及其全部 `file`；另需 `live-opening-2772.png`、`live-own-2772.png`、`daily-popup-2772.png`。
- `aspect-169-probe/manifest.json` 及其全部 `file`。
- `opening-retention-probe/manifest.json` 及其 `files`。
- `phone-inset-probe/` 下的 `phone114-battle-review.jpg`、`phone114-menu-review.jpg`、`phone116-mulligan-review.jpg`、`phone121-settle-review.jpg`。
- `phone-result-probe/original.png`。
- `opening-opponent-wait-probe/code139-frame0008-review.jpg`，须符合 `OpeningEvidenceReplayChecks` 中的原有哈希及等待状态契约。
- `dynamic-menu-probe/` 下的 `code125-home-720-review.jpg`、`code128-promotion-review.jpg`、`code129-daily-review.jpg`、`code130-starter-original.png`。

各专用回放的画面内容、清单期望值和源码断言必须一致。不能用任意图片填补缺失的专项样本。目标应用中的 `mobile-core`、`match-entry`、`mulligan-one-shot` 和 `native-ocr` 运行资产仍按原构建校验准备。

从本目录执行：

```text
python tools/verify_release_smoke_assets.py
python tools/prepare_public_release_test_support.py
```

第二个工具先执行同一素材预检，再生成纯测试 Python 源码资产。它不复制图片，也不把测试源码加入正式 APK。设备检查仍须针对实际正式包运行，并单独核实版本、包哈希、12 组结果、零输入及清理结果。

# 手机版源码

本目录说明 Android **0.2.3 / versionCode 151** 的独立源码快照。项目位于 [`android-app/`](android-app/)，包括 Java 界面与无障碍边界、Python 识别/行动模块、内置引擎、OCR 模型和识别模板。PC 源码在仓库根目录的 `src/`，两条维护线分开。

手机版源码固定到提交 [`a2af64b906fb621ada347a868ada7c0c0cdadbb4`](https://github.com/yumehanab1/OCR-Kards-Auto/tree/a2af64b906fb621ada347a868ada7c0c0cdadbb4/mobile/source/android-app)。共享 `v0.2.3` 标签保留为既有 PC 发布提交，手机版源码以此不可变链接为准。正式151包已完成构建、签名、安装、API35设备发布12组及78项截图专项、浮窗状态组，均零游戏输入；公开附件及匿名下载核验见发布报告。

直接安装请使用同页 [v0.2.3 Release](https://github.com/yumehanab1/OCR-Kards-Auto/releases/tag/v0.2.3) 的 [KARDS-AUTO-Mobile-v0.2.3.apk](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.3/KARDS-AUTO-Mobile-v0.2.3.apk)。[安装说明](../README.md)及[公开验证报告](../../docs/reports/mobile/APK_0.2.3_RELEASE.md)。APK 不用另装 Python、ADB 或 PC 软件。

## 构建

需要JDK17、Android SDK35和CPython3.10。Gradle8.7与Chaquopy17由项目配置固定；运行库依赖首次构建需联网下载。设置`ANDROID_HOME`，或在本机创建不提交的`android-app/local.properties`指定SDK。通过`KARDS_BUILD_PYTHON`指定CPython3.10可执行文件。

```powershell
cd android-app
$env:KARDS_BUILD_PYTHON = '你的Python3.10可执行文件路径'
$env:KARDS_PUBLIC_BUILD = 'true'
.\gradlew.bat assembleRelease lintRelease
```

未配置签名时生成 `app/build/outputs/apk/release/app-release-unsigned.apk`。发布签名通过本机环境变量 `KARDS_ANDROID_KEYSTORE`、`KARDS_ANDROID_KEY_ALIAS`、`KARDS_ANDROID_STORE_PASSWORD`、`KARDS_ANDROID_KEY_PASSWORD` 提供；私钥、密码和本机路径不入仓库。本次正式包沿用既有证书，升级验证结果见发布报告；自行构建的不同证书 APK 不能覆盖官方包。

内置引擎自带230文件SHA-256清单。独立源码克隆构建检查这一完整载荷；原维护环境还可与其外部原始源码逐字节核对。不要从PC源码覆盖内置引擎。手动检查：

```powershell
python tools/prepare_mobile_core.py --check --packaged-only
```

源码提交的 Git archive 已核对573个文件、23,471,078 bytes，预期文件集合完整、提交与工作副本原字节一致。内置引擎230个文件、943,893 bytes的清单检查通过。公开副本仅净化 `apk_settle.py` 模块文档字符串中的本机路径，其他AST未变；源码正文检查未发现私有路径。

私有实机截图、原始日志、回放图片和构建/运行环境不上传。Python 测试及 Android 测试源代码保留，需要真实图像的回归须自行准备测试资产；没有这些资产不能将相应回放记为通过。正式 APK 已核对排除测试模块和私有夹具，保留运行必需的模型、裁剪模板与蓝图纹理 atlas/mask，详情见发布报告。

正式151与 code150 开发包的546个 `app/src/main` 文件集合和字节完全一致，`app/build.gradle.kts` 仅修改版本号与名称；这项比较不覆盖全项目，也不表示两包哈希相同。code150 在 Android15/API35 同一会话连续完成3局，正式151只新增零输入的组件验证，没有151同哈希完整对局。code147 的 API32 MuMu 十局和原148正式构建保留为独立历史，不合并成跨包连续局数。

旧兼容投影重启后的虚拟屏旋转修正尚未内置；OBS底层黑屏、实体手机及跨重启长时稳定性未验收。普通效果未知、结束未确认及当前识别范围见[发布报告](../../docs/reports/mobile/APK_0.2.3_RELEASE.md)。

历史：[0.2.2发布报告](../../docs/reports/mobile/APK_0.2.2_RELEASE.md)、[0.2.1 APK](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.1/KARDS-AUTO-Mobile-v0.2.1.apk)及[0.2.1 发布报告](../../docs/reports/mobile/APK_0.2.1_RELEASE.md)。

正式包会排除 Python 测试模块。开发者在准备好自行提供的回放资产后，可先运行 `python tools/prepare_public_release_test_support.py`，再构建 AndroidTest APK；该工具仅生成测试专用源码资产，不加入正式 APK。嵌入引擎使用逐文件哈希校验，`mobile/.gitattributes` 保留源码原始字节，避免跨平台换行转换破坏清单。

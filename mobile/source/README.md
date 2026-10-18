# 手机版源码

本目录说明 Android **0.2.3 / versionCode 148** 的独立源码快照。项目位于 [`android-app/`](android-app/)，包括 Java 界面与无障碍边界、Python 识别/行动模块、内置引擎、OCR 模型和识别模板。PC 源码在仓库根目录的 `src/`，两条维护线分开。

手机版源码固定到提交 [`8a3961618146a189ded1df13b599db7203fba79c`](https://github.com/yumehanab1/OCR-Kards-Auto/tree/8a3961618146a189ded1df13b599db7203fba79c/mobile/source/android-app)。共享 `v0.2.3` 标签保留为既有 PC 发布提交，手机版源码以此不可变链接为准。正式包构建、安装、组件检查及附件校验结果见发布报告。

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

源码提交的 Git archive 已核对571个文件、23,428,399 bytes，预期文件集合完整、提交与工作副本原字节一致。内置引擎230个文件、943,893 bytes的清单检查通过。公开副本仅净化 `apk_settle.py` 模块文档字符串中的本机路径，其他AST未变；源码正文检查未发现私有路径。

私有实机截图、原始日志、回放图片和构建/运行环境不上传。Python 测试及 Android 测试源代码保留，需要真实图像的回归须自行准备测试资产；没有这些资产不能将相应回放记为通过。正式 APK 已核对排除测试模块和私有夹具，保留运行必需的模型、裁剪模板与蓝图纹理 atlas/mask，详情见发布报告。

开发包 code147 的 API32 MuMu 同包十局与正式 code148 构建分别记录，不能把开发包对局验证记到重新构建的正式 APK 上。兼容截图通道、宿主虚拟屏旋转调整、67次普通效果未知及1次结束未确认的范围见[发布报告](../../docs/reports/mobile/APK_0.2.3_RELEASE.md)。实体手机和更长时间稳定性未由此次测试覆盖。

历史：[0.2.2发布报告](../../docs/reports/mobile/APK_0.2.2_RELEASE.md)、[0.2.1 APK](https://github.com/yumehanab1/OCR-Kards-Auto/releases/download/v0.2.1/KARDS-AUTO-Mobile-v0.2.1.apk)及[0.2.1 发布报告](../../docs/reports/mobile/APK_0.2.1_RELEASE.md)。

正式包会排除 Python 测试模块。开发者在准备好自行提供的回放资产后，可先运行 `python tools/prepare_public_release_test_support.py`，再构建 AndroidTest APK；该工具仅生成测试专用源码资产，不加入正式 APK。嵌入引擎使用逐文件哈希校验，`mobile/.gitattributes` 保留源码原始字节，避免跨平台换行转换破坏清单。

# 贡献指南

## 先看

- [README](README.md)：安装和使用
- [架构](docs/architecture.md)：运行链路与文件归属
- [文档索引](docs/README.md)：设计、生成物、PC/手游报告
- [NOTICE](NOTICE.md)：授权与自动化风险

## 环境

```cmd
install.cmd
.venv\Scripts\python.exe src\main_loop.py --play --fast-scan --attack --max-rounds 1
```

要求 Python 3.10+。发布仓库不提交便携 `python/`、exe、日志和截图。

## 回归检查

在仓库根目录运行；不需要游戏窗口：

```cmd
.venv\Scripts\python.exe dev\gui_test.py
.venv\Scripts\python.exe dev\actions_test.py
.venv\Scripts\python.exe dev\update_check_test.py
.venv\Scripts\python.exe dev\orders_test.py
.venv\Scripts\python.exe dev\dismiss_test.py
```

识别判据改动还要用真实帧做 A/B；需要窗口的工具会在脚本说明中标明。完整工具索引见 [`dev/README.md`](dev/README.md)。

## 目录规则

- 运行时模块放 `src/`；旧实验放 `src/archive/`。
- 测试和探针放 `dev/`，并在 `dev/README.md` 登记。
- 设计放 `docs/design/`，生成文档放 `docs/generated/`，实机报告放 `docs/reports/`。
- 手游/Android 是独立维护线，放 `docs/reports/mobile/`，不得因 PC 整理删除。
- 临时截图和日志只放 `shots/`、`logs/`。
- 根目录只放入口、构建脚本、依赖和顶层说明。

## 改动纪律

1. 失败路径必须写出证据，不能静默吞错。
2. 识别判据先做真实帧 A/B，再改阈值。
3. 保留可快速关闭的开关；默认行为要安全停手。
4. 改 `src/gui.py` 必须重打 exe；改引擎无需重打。
5. 行为变化同步更新 `CHANGELOG.md`；版本号只在发版时改。

## 发布

1. 跑回归检查。
2. 更新 `config/app_version.json` 和 `CHANGELOG.md`。
3. 改过 `src/gui.py` 就运行 `build_gui.bat`。
4. 运行 `python\\python.exe make_release.py`，确认自检通过。
5. 把 zip 解压到空目录，检查版本、卡库和费用模板，再创建 GitHub Release。

提交信息用中文，说明改了什么、为什么、如何验证。不要提交面板 token、账号昵称、完整日志或本机绝对路径。
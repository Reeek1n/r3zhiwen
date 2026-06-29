# macOS 指纹浏览器

这个工作区用本机 `Chromium.app` 或 `Google Chrome.app` 生成多个独立资料窗口：

- 有一个资料管理器 App，可以创建、打开资料
- 每个资料是一个单独的 `.app`
- 每个 `.app` 有独立 `CFBundleIdentifier`
- 每个图标右下角显示编号
- 每个资料使用独立 `--user-data-dir`
- 每个资料可以带独立 `--fingerprint` 种子和启动参数

## 管理器 App

生成管理器：

```bash
/usr/bin/python3 tools/create_manager_app.py
```

然后打开：

```bash
open "指纹浏览器.app"
```

在管理器里点 `创建资料` 会创建一个新资料，并立刻打开一个独立浏览器窗口。双击列表里的资料，或点 `打开窗口`，会再次打开该资料。

管理器会自动优先查找：

- `/Applications/Chromium.app`
- `/Applications/Google Chrome.app`

如果两者都没有，再手动选择浏览器路径。

资料会保存到 `~/Library/Application Support/指纹浏览器/profiles/profiles.json`，浏览器数据保存在 `~/Library/Application Support/指纹浏览器/profiles/profile-N`。下次打开 `指纹浏览器.app`，列表会自动恢复；如果配置文件丢失，也会扫描 `~/Library/Application Support/指纹浏览器/apps` 自动找回。

创建窗口弹窗当前支持：

- 窗口名称、代理、语言、时区、备注
- Cookie JSON 导入
- 启动后打开指定网址
- 启动参数，每行一个
- 结构化指纹配置：平台、Chrome 版本、User-Agent、窗口尺寸、DPR、CPU 核数、内存、WebRTC 策略

结构化指纹配置会保存到 `profiles/profiles.json`，并映射成启动参数，例如 `--user-agent`、`--window-size`、`--force-device-scale-factor`、`--fingerprint-platform`、`--fingerprint-hardware-concurrency`。

## 本地 API

启动：

```bash
FINGERPRINT_API_KEY=local-dev-key /usr/bin/python3 tools/local_api.py
```

接口默认监听 `http://127.0.0.1:18787`，请求头需要带：

```text
X-API-Key: local-dev-key
```

常用接口：

```bash
curl -H 'X-API-Key: local-dev-key' http://127.0.0.1:18787/profiles

curl -X POST -H 'X-API-Key: local-dev-key' -H 'Content-Type: application/json' \
  http://127.0.0.1:18787/profiles \
  -d '{"name":"资料","proxy":"","open_urls":["https://example.com"],"cookie_json":"[]","fingerprint_config":{"platform":"macos","chrome_version":"148","width":1280,"height":720,"device_scale_factor":"1","cpu_cores":8,"memory_gb":8,"webrtc_policy":"disable-non-proxied-udp"}}'

curl -X POST -H 'X-API-Key: local-dev-key' http://127.0.0.1:18787/profiles/1/open
curl -X POST -H 'X-API-Key: local-dev-key' http://127.0.0.1:18787/profiles/1/close
curl -X POST -H 'X-API-Key: local-dev-key' http://127.0.0.1:18787/profiles/1/clear
curl -X PATCH -H 'X-API-Key: local-dev-key' -H 'Content-Type: application/json' \
  http://127.0.0.1:18787/profiles/1 \
  -d '{"remark":"备注"}'
curl -X DELETE -H 'X-API-Key: local-dev-key' http://127.0.0.1:18787/profiles/1
curl -X POST -H 'X-API-Key: local-dev-key' http://127.0.0.1:18787/profiles/open_all
curl -X POST -H 'X-API-Key: local-dev-key' http://127.0.0.1:18787/profiles/close_all
curl -H 'X-API-Key: local-dev-key' http://127.0.0.1:18787/templates
curl -X POST -H 'X-API-Key: local-dev-key' -H 'Content-Type: application/json' \
  http://127.0.0.1:18787/profiles/batch \
  -d '{"count":5,"name":"资料"}'
```

## 环境管理

GUI 目前支持：

- 创建窗口
- 打开/关闭单个窗口
- 打开全部/关闭全部
- 共享扩展管理（统一导入，所有窗口可用）
- 清空选中环境缓存
- 删除选中环境及对应 App/资料目录
- 导入/导出 `profiles.json` 配置

共享扩展的行为是：

- 扩展目录只保存一份，配置文件在 `profiles/shared_extensions.json`
- 所有窗口启动时都会自动加载这些扩展
- 每个窗口仍然使用自己的 `--user-data-dir`
- 所以扩展的设置、缓存、登录状态、存储数据仍然彼此隔离

## 模板和批量创建

默认模板在：

```text
templates/default.json
```

GUI 顶部的 `批量创建` 可以一次创建多个环境，默认不会自动打开窗口。API 也支持 `POST /profiles/batch`。

## 批量生成

```bash
/usr/bin/python3 tools/create_fingerprint_profiles.py --count 5 --force
```

生成结果：

- `apps/资料 1.app`
- `apps/资料 2.app`
- `apps/资料 3.app`
- `profiles/profile-1`
- `profiles/profile-2`
- `profiles/profile-3`

双击不同的 `资料 N.app`，macOS Dock 会显示不同编号图标。

## 选项

指定 Chromium：

```bash
/usr/bin/python3 tools/create_fingerprint_profiles.py \
  --source-app /Applications/Chromium.app \
  --count 10 \
  --force
```

改名字：

```bash
/usr/bin/python3 tools/create_fingerprint_profiles.py --app-name "资料" --count 10 --force
```

添加 Chromium 启动参数：

```bash
/usr/bin/python3 tools/create_fingerprint_profiles.py \
  --count 5 \
  --extra-arg="--lang=zh-CN" \
  --force
```

配合 `adryfish/fingerprint-chromium` 使用时，给每个资料自动分配不同指纹种子：

```bash
/usr/bin/python3 tools/create_fingerprint_profiles.py \
  --source-app /Applications/Chromium.app \
  --count 10 \
  --fingerprint-base 10000 \
  --extra-arg="--fingerprint-platform=macos" \
  --extra-arg="--lang=zh-CN" \
  --extra-arg="--timezone=Asia/Shanghai" \
  --force
```

## 说明

这里先实现你明确提出的要求：多个资料打开时有多个 macOS 图标，并且图标显示编号。

如果后续要做更完整的“指纹浏览器”，建议在这个基础上继续加资料配置，例如代理、语言、时区、UA、WebRTC 策略和权限默认值。不要用它绕过网站规则或平台风控。

## Windows 版本骨架

现在工作区里已经补了一套 Windows 版骨架，和 mac 版分开存放，避免互相覆盖：

- 配置文件：`profiles/profiles.windows.json`
- 启动器目录：`apps_windows/profile-N/窗口名/`
- 浏览器数据目录：`profiles_windows/profile-N`
- 管理器脚本：`tools/windows_manager.py`
- 批量创建脚本：`tools/create_windows_profiles.py`

Windows 版当前设计：

- 每个窗口一个独立资料目录
- 每个窗口生成 `.cmd` 启动器、`.vbs` 隐藏启动入口、`.ico` 编号图标
- 默认优先使用本机已安装的外置 `Chrome`
- 支持 Cookie 导入
- 支持启动后打开指定网址
- 支持代理、语言、时区、基础指纹参数
- 与 mac 配置隔离，不会改动 `profiles/profiles.json`

Windows 上运行管理器：

```bash
python tools/windows_manager.py
```

Windows 上批量创建：

```bash
python tools/create_windows_profiles.py --count 5 --force
```

如果 Chromium 不在默认路径，可以指定：

```bash
python tools/create_windows_profiles.py ^
  --source-exe "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
  --count 5 ^
  --force
```

当前这部分是第一版骨架，目标先放在“创建、保存、再次打开”这条链打通。真正的 Windows 打包、任务栏快捷方式、`.lnk` 生成和更完整的本地 API，还可以继续往下补。

## Windows 打包 exe

Windows 上安装依赖：

```bash
py -m pip install pyinstaller pillow
```

打包管理器 exe：

```bash
py tools/build_windows_exe.py
```

默认输出目录：

```text
dist_windows/指纹浏览器-Windows/
```

如果你想打成带控制台窗口版本：

```bash
py tools/build_windows_exe.py --console
```

如果你不想手动敲命令，可以直接双击：

```text
build_windows.bat
```

这个脚本会自动：

- 检查 Python
- 安装 `pyinstaller` 和 `pillow`
- 开始打包
- 打开输出目录
- 在失败时写日志到 `logs/build_windows.log`

Windows 版会按这个顺序找浏览器：

1. `C:\Program Files\Google\Chrome\Application\chrome.exe`
2. `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`
3. `C:\Program Files\Chromium\Application\chrome.exe`
4. `C:\Program Files (x86)\Chromium\Application\chrome.exe`

如果都没找到，就在管理器里手动选择 `chrome.exe`。

如果 Windows 管理器双击后直接闪退，请先查看日志文件：

```text
logs/windows_manager.log
```

现在启动失败时会尝试弹出错误框，并把异常写进这个日志文件。

## Windows 安装包

如果你想进一步生成真正的安装包，可以使用 `Inno Setup 6`。

安装包脚本：

```text
windows_installer.iss
```

一键安装包脚本：

```text
build_windows_installer.bat
```

这个脚本会：

- 先检查 `dist_windows/指纹浏览器-Windows/` 是否存在
- 如果不存在，先调用 `build_windows.bat`
- 再调用 `Inno Setup 6` 生成安装包
- 最后打开安装包输出目录

默认安装包输出：

```text
installer_dist/FingerprintBrowserWindowsSetup.exe
```

如果安装包打包失败，请查看：

```text
logs/build_windows_installer.log
```

# tgtranslate — Serv00 部署指南 / Serv00 deployment guide

需要连接 BotFather 创建的 Telegram bot？请使用独立的 [仅翻译 bot 部署指南](BOT_DEPLOY.md)。原有 `tg_auto_translate.py` 仍是用户账号客户端。

[中文](#中文) · [English](#english)

基于 Telethon 的 Telegram **用户账号客户端**：按聊天规则自动翻译消息，也可用 `.fy` 指令临时翻译。它使用 Telegram `api_id`、`api_hash` 和登录会话，**不使用 BotFather token**；通过长连接运行，无须配置网站、域名或入站端口。

A Telethon based Telegram **user account client**. It translates messages according to chat rules and supports one off translations with `.fy` commands. It uses a Telegram `api_id`, `api_hash`, and login session, **not a BotFather token**. It runs over an outbound connection; no website, domain, or inbound port is needed.

## 中文

### 准备

- Serv00 账号及其 SSH 登录名和服务器地址（以开通邮件为准）。
- Telegram 用户账号，以及从 [Telegram API development tools](https://my.telegram.org/apps) 获取的 `api_id` 和 `api_hash`。
- 至少一个可用的翻译接口：Gemini 原生 API、OpenAI 兼容接口，或 DeepLX。示例配置中的 `YOUR_*`、模型名称和网址只是占位符，必须换成实际可用的值。
- Serv00 上的 Python 3.11、`virtualenv` 和 Git。`fasttext` 是含原生扩展的依赖，在 FreeBSD 上可能需要编译。

### 1. 登录并安装

在本地终端登录，将 `LOGIN` 和 `sX.serv00.com` 换成开通邮件中的值：

```sh
ssh LOGIN@sX.serv00.com
```

在 Serv00 面板启用 **Run your own applications / Binexec**，或在 SSH 中执行 `devil binexec on`，然后退出并重新登录。接着运行：

```sh
cd ~
git clone --branch serv00-deploy --single-branch https://github.com/fsyllkn/tgtranslate.git
cd tgtranslate
mkdir -p ~/.virtualenvs
virtualenv -p /usr/local/bin/python3.11 ~/.virtualenvs/tgtranslate
source ~/.virtualenvs/tgtranslate/bin/activate
python -m pip install -r requirements.txt
```

虚拟环境放在仓库之外，后续更新代码时不会影响依赖。若 `fasttext` 编译失败，请参阅下方“常见问题”。

### 2. 配置 Telegram 和翻译接口

```sh
cd ~/tgtranslate
umask 077
cp config.sample.yaml config.yaml
chmod 600 config.yaml
ee config.yaml
```
```sh
编辑完成后，按 Esc 跳出 ee 菜单，默认退出编辑（Leave editor）；enter确认，再次enter确认，就保存退出编辑
```

至少检查这些配置项（以 [`config.sample.yaml`](config.sample.yaml) 为完整模板）：

| 配置 | 作用 |
| --- | --- |
| `telegram.api_id` / `telegram.api_hash` | 自己的 Telegram API 凭据；`api_id` 是数字。 |
| `telegram.session_name` | 会话文件名；默认示例 `translate` 会在项目目录生成 `translate.session`。 |
| `telegram.my_tg_ids` | 允许使用全部 `.fy` 指令的 Telegram **用户数字 ID** 列表，不是手机号或用户名。 |
| `default_translate_source` | 首选引擎：`gemini`、`openai` 或 `deeplx`。 |
| `translation_engine_order` | 首选引擎失败后的回退优先顺序；程序还会尝试其他已配置的引擎。 |
| `gemini.model_groups` / `openai.model_groups` | 每组实际支持的模型及端点 `url`、`api_key`。Gemini 使用原生 `/v1beta` 接口；OpenAI 使用兼容 `/v1/chat/completions` 的接口。 |
| `deeplx.enabled` / `deeplx.base_urls` | 使用 DeepLX 时启用并填写完整的 `/translate` 地址。 |
| `language_detection.primary_language` | 主语言，示例为 `zh`。 |
| `fasttext.enabled` / `fasttext.model_path` | 是否加载 fastText 语言识别模型及其文件路径。 |

保留至少一个真正可用的引擎，并删除其他引擎的示例占位端点。例如只用 Gemini 时，填写真实 `gemini.model_groups`，把 `openai.model_groups` 改为 `[]`，保持 `deeplx.enabled: false`。模型 ID 应以供应商当前实际提供的名称为准。

示例默认启用 fastText，并寻找项目根目录下的 `lid.176.bin`。下载 [fastText 官方模型](https://fasttext.cc/docs/en/language-identification.html)：

```sh
cd ~/tgtranslate
curl -fL https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin -o lid.176.bin
```

该模型约 126 MB。若想使用官方压缩版，可下载 `lid.176.ftz`，并把 `fasttext.model_path` 改为 `lid.176.ftz`；若不使用 fastText，设置 `fasttext.enabled: false`，语言识别会使用代码中的其他判断方法，但准确度可能下降。不要将模型文件提交到 Git。

### 3. 首次前台登录和试用

**从仓库根目录启动**，因为程序用相对路径读取 `config.yaml`，并在这里保存会话、规则和运行时设置：

```sh
cd ~/tgtranslate
source ~/.virtualenvs/tgtranslate/bin/activate
python -u tg_auto_translate.py
```

首次运行按 Telethon 提示输入手机号、Telegram 验证码，以及账号启用时的两步验证密码。看到 `Telegram 客户端已启动，等待消息...` 后，登录会话已保存。先在 Telegram 中用白名单账号发送 `.fy-help` 或 `.fy-main` 测试。按 `Ctrl+C` 停止前台进程。

初始没有自动翻译规则。在需要翻译的私聊或群聊中，使用 `.fy-on` 为自己的消息启用“非主语言 → 主语言”规则；在私聊中使用 `.fy-add` 为对方消息启用规则。常用指令：

| 指令 | 用途 |
| --- | --- |
| `.fy-help` | 查看完整指令帮助。 |
| `.fy-main,zh` / `.fy-main,off` | 设置主语言 / 关闭主语言模式。 |
| `.fy-on` / `.fy-off` | 在当前聊天中启用 / 关闭自己的自动翻译。 |
| `.fy-add` / `.fy-del` | 在私聊中启用 / 关闭对方消息翻译；群聊可用 `.fy-add,成员ID` 指定成员。 |
| `.fy-en 文本` 或回复消息后发送 `.fy-en` | 临时翻译为英语；`.fy` 使用主语言。 |
| `.fy-list` / `.fy-clear` | 列出 / 清空已保存规则。 |
| `.fy-reload` | 重新读取 `config.yaml` 和翻译引擎配置。 |

指令只响应 `telegram.my_tg_ids` 中的用户。规则保存到 `dynamic_rules.json`；`.fy-main` 修改的主语言设置保存到 `runtime_settings.json`。这两个文件及 `*.session`、`config.yaml` 均不应公开或提交。

### 4. 后台运行、日志与开机启动

完成首次交互登录后，再从项目根目录后台启动：

```sh
cd ~/tgtranslate
nohup ~/.virtualenvs/tgtranslate/bin/python -u tg_auto_translate.py >> bot.log 2>&1 < /dev/null &
tail -f bot.log
```

SSH 断开后可用 `ps -u "$USER" -o pid,command | grep '[t]g_auto_translate.py'` 检查进程；停止时对查到的 PID 执行 `kill PID`。不要同时启动两个实例使用同一个 Telegram 会话。

如需服务器重启后自动启动，运行 `crontab -e`，添加下面一行，并将所有 `LOGIN` 替换为自己的登录名：

```cron
@reboot cd /usr/home/LOGIN/tgtranslate && /usr/home/LOGIN/.virtualenvs/tgtranslate/bin/python -u tg_auto_translate.py >> /usr/home/LOGIN/tgtranslate/bot.log 2>&1
```

`@reboot` 只在服务器重启时启动；进程之后异常退出时，需要手动检查日志并重启。请遵守 Serv00 的进程和资源限制。

### 5. 进程保活 / Process watchdog

保活脚本不能阻止 Serv00 或系统终止进程；它只会定时检查进程是否存在，发现进程消失后重新创建 tmux 会话。每 5 分钟检查一次，异常退出后的恢复时间最长约 5 分钟。

创建 ~/bin/check_tgtranslate.sh：

~~~sh
mkdir -p ~/bin
nano ~/bin/check_tgtranslate.sh
~~~

写入：

~~~sh
#!/bin/sh

APP_DIR="$HOME/tgtranslate"
PYTHON="$HOME/.virtualenvs/tgtranslate/bin/python"
SESSION="tgtranslate"
LOG="$APP_DIR/bot.log"
WATCHDOG_LOG="$APP_DIR/watchdog.log"
ME="$(id -un)"

# ps/awk 比 pgrep -u 更适合不同的 Serv00 shell 环境。
if ps auxww | awk -v me="$ME" \
    '$1 == me && /[p]ython[^ ]* .*tg_auto_translate[.]py/ { found=1 }
     END { exit(found ? 0 : 1) }'
then
    printf '%s process ok\n' "$(date '+%F %T')" >> "$WATCHDOG_LOG"
    exit 0
fi

printf '%s process missing, restarting\n' "$(date '+%F %T')" >> "$WATCHDOG_LOG"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
fi

tmux new-session -d -s "$SESSION" \
    "cd '$APP_DIR' && exec '$PYTHON' -u tg_auto_translate.py >> '$LOG' 2>&1"
~~~

然后：

~~~sh
chmod +x ~/bin/check_tgtranslate.sh
~/bin/check_tgtranslate.sh
tail -n 5 ~/tgtranslate/watchdog.log
~~~

正常运行时应看到 process ok。如果脚本报告 process missing, restarting，但下面命令能看到 Python 进程，应先修正检查脚本，不要启用 cron，以免误杀正常的 tmux 会话：

~~~sh
ps auxww | grep '[t]g_auto_translate.py'
tmux ls
~~~

将原来直接启动 Python 的 @reboot 行替换为以下两行。把 /home/LOGIN 替换成 echo "$HOME" 输出的实际路径：

~~~cron
*/5 * * * * /usr/local/bin/flock /home/LOGIN/tgtranslate/watchdog.lock /home/LOGIN/bin/check_tgtranslate.sh >> /home/LOGIN/tgtranslate/cron.log 2>&1
@reboot /home/LOGIN/bin/check_tgtranslate.sh
~~~

flock 防止检查任务重叠。只保留一组 watchdog cron；不要同时使用 screen、多个 tmux 会话、多个 @reboot、手动启动和 watchdog 启动，否则可能产生多个 Telegram session 进程。

保活只能恢复“进程不存在”的情况，不能判断 Python 已经卡住或 Telegram 连接已失效。如果 Serv00 账号被封、Processes/RAM 达到限制，watchdog 也可能无法启动新进程。Account is now banned in <channel> 是 Telegram 对特定频道的访问限制，不是 Serv00 进程故障，重启不能解除。

查看资源：

~~~sh
ps auxww | awk -v u="$USER" '$1 == u {rss += $6; cpu += $3; n++} END {printf "processes=%d CPU=%.1f%% RSS=%.1f MB\n", n, cpu, rss/1024}'
tail -f ~/tgtranslate/watchdog.log
~~~

RSS 是实际内存，VSZ 是虚拟地址空间；不要把 VSZ 当作实际 RAM。重点观察 RSS 是否持续增长，以及 DevilWEB 的 Processes/RAM 是否接近 100%。


### 更新与常见问题

更新前先停止旧进程，再执行：

```sh
cd ~/tgtranslate
git pull --ff-only origin serv00-deploy
source ~/.virtualenvs/tgtranslate/bin/activate
python -m pip install -r requirements.txt
```

然后按上面的后台命令重启。`config.yaml`、Telegram 会话及规则文件被 `.gitignore` 排除，升级前仍建议自行备份。

- **`fasttext` 安装失败**：参照 [Serv00 Python 文档](https://docs.serv00.com/Python/) 设置 `CFLAGS="-I/usr/local/include"`、`CXXFLAGS="-I/usr/local/include"`，必要时使用 `CC=gcc CXX=g++` 或 `MAX_CONCURRENCY=1 CPUCOUNT=1 MAKEFLAGS=-j1` 后重试 `python -m pip install fasttext`。
- **提示模型不存在**：确认 `fasttext.model_path` 指向已下载文件，或设置 `fasttext.enabled: false`。
- **首次登录后没有翻译**：确认 `telegram.my_tg_ids` 包含发送指令的用户数字 ID，翻译端点真实可用，并在目标聊天用 `.fy-on` 或 `.fy-add` 建立规则；查看 `bot.log` 排错。
- **修改配置未生效**：发送 `.fy-reload`；如果程序尚未登录，直接重启进程。更换 `session_name` 会改用新的会话文件，通常需要重新登录。
- **后台进程等待验证码**：先在前台完成一次 Telegram 登录，再后台启动。

参考：[Serv00 登录](https://docs.serv00.com/Login/) · [Binexec](https://docs.serv00.com/Binexec/) · [Python](https://docs.serv00.com/Python/) · [Cron](https://docs.serv00.com/Cron/) · [Telegram API ID](https://core.telegram.org/api/obtaining_api_id)

## English

### Prerequisites

- A Serv00 account, SSH login, and server address from the activation email.
- A Telegram user account and its `api_id` and `api_hash` from [Telegram API development tools](https://my.telegram.org/apps).
- At least one working translation endpoint: native Gemini API, an OpenAI compatible API, or DeepLX. The sample's `YOUR_*` values, model IDs, and URLs are placeholders.
- Python 3.11, `virtualenv`, and Git on Serv00. `fasttext` contains a native extension and may need to compile on FreeBSD.

### 1. Connect and install

Replace `LOGIN` and `sX.serv00.com` with the values from your Serv00 activation email:

```sh
ssh LOGIN@sX.serv00.com
```

Enable **Run your own applications / Binexec** in the Serv00 panel, or run `devil binexec on` over SSH, then log out and reconnect. Install the project:

```sh
cd ~
git clone --branch serv00-deploy --single-branch https://github.com/fsyllkn/tgtranslate.git
cd tgtranslate
mkdir -p ~/.virtualenvs
virtualenv -p /usr/local/bin/python3.11 ~/.virtualenvs/tgtranslate
source ~/.virtualenvs/tgtranslate/bin/activate
python -m pip install -r requirements.txt
```

The virtual environment lives outside the repository. See Troubleshooting if building `fasttext` fails.

### 2. Configure Telegram and translation

```sh
cd ~/tgtranslate
umask 077
cp config.sample.yaml config.yaml
chmod 600 config.yaml
ee config.yaml
```

Review at least these keys in [`config.sample.yaml`](config.sample.yaml):

| Key | Purpose |
| --- | --- |
| `telegram.api_id` / `telegram.api_hash` | Your Telegram API credentials; `api_id` is numeric. |
| `telegram.session_name` | Session filename; the sample value `translate` produces `translate.session` in the project directory. |
| `telegram.my_tg_ids` | Numeric Telegram **user IDs** allowed to run every `.fy` command; not phone numbers or usernames. |
| `default_translate_source` | Preferred engine: `gemini`, `openai`, or `deeplx`. |
| `translation_engine_order` | Failover priority after the preferred engine; the program also tries other configured engines. |
| `gemini.model_groups` / `openai.model_groups` | Supported model IDs and endpoint `url` / `api_key`. Gemini uses its native `/v1beta` API; OpenAI uses an API compatible with `/v1/chat/completions`. |
| `deeplx.enabled` / `deeplx.base_urls` | Enable DeepLX and supply complete `/translate` URLs if needed. |
| `language_detection.primary_language` | Primary language; `zh` in the sample. |
| `fasttext.enabled` / `fasttext.model_path` | Whether to load the fastText language model and where it is stored. |

Keep at least one real endpoint and remove unused placeholder endpoints. For a Gemini only setup, fill in a working `gemini.model_groups`, set `openai.model_groups: []`, and leave `deeplx.enabled: false`. Use model IDs currently offered by your provider.

The sample enables fastText and expects `lid.176.bin` in the project root. Download the [official fastText model](https://fasttext.cc/docs/en/language-identification.html):

```sh
cd ~/tgtranslate
curl -fL https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin -o lid.176.bin
```

This model is about 126 MB. Alternatively, download the official `lid.176.ftz` and set `fasttext.model_path: "lid.176.ftz"`. To run without it, set `fasttext.enabled: false`; the code will use its other language detection methods, with potentially lower accuracy. Do not commit model files.

### 3. First interactive login and test

**Run from the repository root**. The program reads `config.yaml` and writes its session, rules, and runtime settings relative to the current directory:

```sh
cd ~/tgtranslate
source ~/.virtualenvs/tgtranslate/bin/activate
python -u tg_auto_translate.py
```

On first launch, enter your phone number, Telegram login code, and two step verification password if enabled. After the log says `Telegram 客户端已启动，等待消息...`, try `.fy-help` or `.fy-main` from a whitelisted account in Telegram. Press `Ctrl+C` to stop the foreground process.

There are no automatic translation rules initially. Use `.fy-on` in a chat to translate your own non primary language messages into the primary language. Use `.fy-add` in a private chat to translate the other person's messages.

| Command | Purpose |
| --- | --- |
| `.fy-help` | Full command help. |
| `.fy-main,zh` / `.fy-main,off` | Set the primary language / disable primary language mode. |
| `.fy-on` / `.fy-off` | Enable / disable automatic translation of your own messages in the current chat. |
| `.fy-add` / `.fy-del` | Enable / disable translation of the other person in a private chat; use `.fy-add,USER_ID` for a group member. |
| `.fy-en text`, or reply with `.fy-en` | Translate once into English; `.fy` uses the primary language. |
| `.fy-list` / `.fy-clear` | List / clear saved rules. |
| `.fy-reload` | Reload `config.yaml` and translation engine settings. |

Only users in `telegram.my_tg_ids` can run commands. Rules are saved in `dynamic_rules.json`; `.fy-main` settings are saved in `runtime_settings.json`. Keep these files, `*.session`, and `config.yaml` private and out of Git.

### 4. Background operation, logs, and startup

After completing the interactive login, start the client in the background from the project root:

```sh
cd ~/tgtranslate
nohup ~/.virtualenvs/tgtranslate/bin/python -u tg_auto_translate.py >> bot.log 2>&1 < /dev/null &
tail -f bot.log
```

After disconnecting SSH, check it with `ps -u "$USER" -o pid,command | grep '[t]g_auto_translate.py'`. Stop it with `kill PID`, using the PID shown by `ps`. Do not run two instances with the same Telegram session.

For startup after a server reboot, run `crontab -e` and add this line, replacing every `LOGIN` with your actual login:

```cron
@reboot cd /usr/home/LOGIN/tgtranslate && /usr/home/LOGIN/.virtualenvs/tgtranslate/bin/python -u tg_auto_translate.py >> /usr/home/LOGIN/tgtranslate/bot.log 2>&1
```

`@reboot` runs only after a server reboot. If the process later exits, inspect the log and restart it manually. Respect Serv00 process and resource limits.

### 5. Process watchdog

The watchdog cannot prevent Serv00 or the operating system from terminating a process. It periodically checks whether the process exists and recreates the tmux session if it is gone. With a five-minute schedule, recovery after an unexpected exit can take up to about five minutes.

Create ~/bin/check_tgtranslate.sh:

~~~sh
mkdir -p ~/bin
nano ~/bin/check_tgtranslate.sh
~~~

Paste:

~~~sh
#!/bin/sh

APP_DIR="$HOME/tgtranslate"
PYTHON="$HOME/.virtualenvs/tgtranslate/bin/python"
SESSION="tgtranslate"
LOG="$APP_DIR/bot.log"
WATCHDOG_LOG="$APP_DIR/watchdog.log"
ME="$(id -un)"

# ps/awk is more reliable than pgrep -u across Serv00 shell environments.
if ps auxww | awk -v me="$ME" \
    '$1 == me && /[p]ython[^ ]* .*tg_auto_translate[.]py/ { found=1 }
     END { exit(found ? 0 : 1) }'
then
    printf '%s process ok\n' "$(date '+%F %T')" >> "$WATCHDOG_LOG"
    exit 0
fi

printf '%s process missing, restarting\n' "$(date '+%F %T')" >> "$WATCHDOG_LOG"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
fi

tmux new-session -d -s "$SESSION" \
    "cd '$APP_DIR' && exec '$PYTHON' -u tg_auto_translate.py >> '$LOG' 2>&1"
~~~

Then run:

~~~sh
chmod +x ~/bin/check_tgtranslate.sh
~/bin/check_tgtranslate.sh
tail -n 5 ~/tgtranslate/watchdog.log
~~~

A healthy check should report process ok. If it reports process missing, restarting while the following commands show a running Python process, fix the check before enabling cron; otherwise a healthy tmux session may be killed:

~~~sh
ps auxww | grep '[t]g_auto_translate.py'
tmux ls
~~~

Replace the existing direct-Python @reboot line with these two lines. Replace /home/LOGIN with the actual path printed by echo "$HOME":

~~~cron
*/5 * * * * /usr/local/bin/flock /home/LOGIN/tgtranslate/watchdog.lock /home/LOGIN/bin/check_tgtranslate.sh >> /home/LOGIN/tgtranslate/cron.log 2>&1
@reboot /home/LOGIN/bin/check_tgtranslate.sh
~~~

flock prevents overlapping checks. Keep only one watchdog configuration. Do not combine multiple screen sessions, multiple tmux sessions, multiple @reboot entries, manual starts, and watchdog starts, or multiple Telegram session processes may be created.

The watchdog only recovers a missing process. It cannot detect a hung Python process or a dead Telegram connection. If the Serv00 account is blocked or its Processes/RAM limits are reached, the watchdog may also be unable to start a replacement. Account is now banned in <channel> is a Telegram restriction for a specific channel, not a Serv00 process failure; restarting cannot remove it.

Check resource usage with:

~~~sh
ps auxww | awk -v u="$USER" '$1 == u {rss += $6; cpu += $3; n++} END {printf "processes=%d CPU=%.1f%% RSS=%.1f MB\n", n, cpu, rss/1024}'
tail -f ~/tgtranslate/watchdog.log
~~~

RSS is resident memory and VSZ is virtual address space; do not treat VSZ as physical RAM. Watch for steadily growing RSS and for Processes/RAM approaching 100% in DevilWEB.


### Updating and troubleshooting

Stop the old process before updating:

```sh
cd ~/tgtranslate
git pull --ff-only origin serv00-deploy
source ~/.virtualenvs/tgtranslate/bin/activate
python -m pip install -r requirements.txt
```

Then restart with the background command above. `config.yaml`, Telegram sessions, and rule files are excluded by `.gitignore`, but back them up before upgrades.

- **`fasttext` fails to build:** Follow the [Serv00 Python guidance](https://docs.serv00.com/Python/): try `CFLAGS="-I/usr/local/include" CXXFLAGS="-I/usr/local/include"`, then `CC=gcc CXX=g++` or `MAX_CONCURRENCY=1 CPUCOUNT=1 MAKEFLAGS=-j1` as needed before retrying `python -m pip install fasttext`.
- **Language model missing:** Check `fasttext.model_path` or set `fasttext.enabled: false`.
- **Logged in but no translation:** Check the numeric ID in `telegram.my_tg_ids`, the configured endpoint, and whether `.fy-on` or `.fy-add` created a rule in that chat. Read `bot.log` for errors.
- **Configuration changes have no effect:** Send `.fy-reload`, or restart if login has not completed. Changing `session_name` selects a new session file and usually requires a new login.
- **Background process waits for a login code:** Complete one interactive login first, then start it in the background.

References: [Serv00 Login](https://docs.serv00.com/Login/) · [Binexec](https://docs.serv00.com/Binexec/) · [Python](https://docs.serv00.com/Python/) · [Cron](https://docs.serv00.com/Cron/) · [Telegram API ID](https://core.telegram.org/api/obtaining_api_id)

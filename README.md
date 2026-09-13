# media-digest — 长剧集压缩观看路线

我没有 30 小时看完一部 74 集的剧，但想完整拿到它的价值。方法是三层：**骨架必看 / 高分独立短篇 / 文字桥接摘要**。这个仓库固化的是"抓数据 + 渲染 + 记进度"这层**骨架**；每部剧的路线内容（哪些集全速看、被跳过的集用什么摘要带过）在各自的 session 里人工写，落进 json 即生效。

> 纯按评分取 top X% 不成立：分集评分分布极窄，且随集数系统性上浮（只有看完的人才给后期集打分）。所以脚本只抓、不排、不算综合分，判断留给人。

## 目录

```
shows/<slug>.json   一部剧一份（数据契约见下）；shows/_schema.json 是 JSON Schema；index.json 由脚本生成
scraper/            抓取 + 校验（本机跑，只写 meta/about/episodes，绝不碰 intro/route）
site/               静态页（GitHub Pages），读 ../shows/<slug>.json，进度存 localStorage
```

## 环境

- Python 用 `py`（本机 `python` 是 Store 占位符）。依赖：`py -m pip install -r scraper/requirements.txt`
- 代理：脚本自动读 `HTTPS_PROXY/HTTP_PROXY`，没有则回退 `127.0.0.1:10808`
- TMDB 可选：key 放环境变量 `TMDB_API_KEY` 或 `scraper/tmdb_api_key.txt`（已 gitignore）

## 跑一遍

```bash
# 找各源 ID（人工确认后再用）
py scraper/fetch.py resolve "Monster"

# 第一次抓：给 ID（缺的源跳过；至少一个）
py scraper/fetch.py monster-2004 --mal 19 --bangumi 1959 --imdb tt0434706 --wiki "List of Monster episodes" --title Monster --title-cn 怪物 --year 2004

# 以后刷新：ID 已在 meta.ids，一条命令；单源失败不拖垮整体、保留上次数据
py scraper/fetch.py monster-2004
py scraper/fetch.py monster-2004 --only mal --no-cache

# 校验（schema + 路线逻辑：越界 / 重叠 / 缺口 / 桥接无正文）
py scraper/validate.py

# 本地看页面
py -m http.server 8765      # 然后开 http://localhost:8765/site/?show=monster-2004
```

## 数据契约（`shows/<slug>.json`）

客观（脚本维护）与主观（session 手写）严格分块，脚本写盘前做深比较断言：**`intro` / `route` 一个字节都不会变**。

| 块 | 谁写 | 内容 |
|---|---|---|
| `meta` | 脚本 | `slug / title / title_cn / title_native / year / total_eps / primary_kpi / updated / schema_version / ids{mal,bangumi,imdb,tmdb,wiki}` |
| `about` | 脚本 | 作品级客观信息：`cover / synopsis{en,zh} / genres / studios / scores{源:{score,votes}} / links / characters[]`（MAL 主角，含头像） |
| `episodes[]` | 脚本 | `n / title_native / title_en / title_cn / aired / synopsis{en,zh} / sources{}`；`sources` 多源**并存不合并**：`mal{score}`、`imdb{rating,votes}`、`tmdb{vote_average,vote_count}`、`bangumi{comments}` |
| `intro` | **人** | 作品介绍：`cover`（覆盖头图）/ `logline` / `synopsis`（**无剧透**）/ `characters[{name,name_cn,role,motivation}]`（按 `name` 与 about 合并头像）/ `highlights[]` / `standing` / `route_note` |
| `episodes[].notes` | **人** | 分集查询手册（含剧透）：`summary` + `new[{name,name_cn,kind: recurring/arc/one-off, note}]`。来自 Drive `episodes.json`。页面点柱状图时：集号 ≤ 已勾选最大集号自动显示（已看过）；未看的点一下按钮才出 |
| `route[]` | **人** | 有序不重叠：`{kind:"watch", eps:[a,b], why}` 或 `{kind:"bridge", eps:[a,b], title, paragraphs:[]}` |

`route` 允许为空——只有 `episodes` 时页面照样渲染（评分曲线 + 全集列表 + 进度）。`intro` 缺项时页面回退到 `about`（并打"自动抓取"标）。

## 无人值守构建（默认路径）

```bash
py scraper/build.py            # 扫 Drive 内容目录：新剧按 route.json 的 meta.ids 抓客观数据 → 全部 sync → 有变更就 commit + push
py scraper/build.py --refresh  # 所有剧重抓评分（建议每周）
run_build.bat                  # 同上，双击即可；计划任务 media-digest-build 每天 09:30 调它（StartWhenAvailable）
```

日志 `scraper/logs/build.log`。某部剧校验不过只跳过它，不影响其余。写内容的会话**不需要任何人通知本机**。双击 bat 时窗口留住并显示结果；计划任务用 `run_build.bat task`（不 pause）。

通用性：多季剧 `meta.season` 只取该季（IMDb/TMDB），不写则按 MAL/Bangumi 声明集数截断；没有评分源的内容（小说）`ids` 留空、给 `meta.total_eps`（+ `unit: 章`）即可建骨架。页面读 json 带时间戳，不受 Pages 10 分钟缓存影响。

## 内容更新回路（Drive → 仓库）

内容不在仓库里写。**Drive 是唯一真相，仓库的 `shows/<slug>.json` 是 build 产物，不手改。** 每部剧的 `route.json`（含 `intro` 块）由各 Claude 会话写到 Drive：

```
<Drive claude根>/domains/personal/media-digest/shows/<slug>/{route.json, intro.json?, cover.jpg?}
```

`sync.py` 会把 chat 会话的键名归一到 schema（`spoiler_free_summary→synopsis`、`character_motivations→characters`、`eps:[4]→[4,4]`），内容不改。

格式与规则见该目录的 `README.md` 和 `_template/`。家里 PC 上：

```bash
py scraper/sync.py monster-2004      # 校验 + 并入 shows/monster-2004.json（整体替换 intro/route，以 Drive 为准）
py scraper/sync.py --all
git push                             # 页面生效
```

`fetch.py` 与 `sync.py` 互不越界：前者只写 meta/about/episodes，后者只写 intro/route（+ 复制封面图到 `site/assets/<slug>/`）。多轮迭代 = 改 Drive 文件再 sync。

## 评分怎么看（页面 KPI）

**各源并存、页面可切、不合并、不加权**（2026-09-13 定）。json 只存原始值。

- **默认 IMDb**（`meta.primary_kpi`）：分辨率最好（Monster 跨度 7.4–9.7，且有票数）；MAL 是 1–5 投票均分、全剧挤在 4.3–4.9，基本是噪音，只做参考；TMDB 覆盖非动画剧；Bangumi API 无分集分。
- 为什么不算综合分：量纲差可以用 z-score 抹平，但**权重给不准**——MAL 没分集票数只能给常数，结果噪音源拿到和 IMDb 几千票差不多的话语权，综合分比 IMDb 单看更糊；而且合并后"哪个源把它顶上去的"没法回答，多源并存的价值就是交叉比对。IMDb 缺失的剧按剧改 `primary_kpi` 即可。
- **热度**是另一个维度，不进评分：`episodes[].heat{mal_replies, bangumi_comments, imdb_votes}`（MAL 论坛回复数最灵：Monster E44 463、E74 727，邻集 100 上下——它标的是剧情爆点，评分标不出来）。页面单独一档「热度」+ 前 10% 打 🔥。
- **去趋势**开关：对当前 KPI 做线性回归扣掉随集数的系统性上浮（只有看完的人才给后期集打分），残差更容易挑出中段的真高分集。
- 单源 tab 显示原始分，柱高按该源 min–max 拉伸。

## 数据源与已知限制

| 源 | 方式 | 给什么 | 限制 |
|---|---|---|---|
| MAL | **全部直抓 HTML**，无需 key、不经 Jikan：`/anime/<id>/_/episode`（分集）、`/anime/<id>`（作品）、`/anime/<id>/_/characters`（角色） | 分集两位小数均分 + 论坛回复数（热度）、日/英/罗马标题、首播日；作品简介、封面、总分/票数/排名、类型、制作公司；主角 + 高人气配角头像 | Jikan 只在 `resolve` 搜索里用，它 504 不影响抓取；robots 对普通 UA 不禁 /anime/ |
| IMDb | 官方数据集 `title.episode` + `title.ratings`（缓存 7 天，~60 MB） | 分集评分 + 票数 | **不爬页面**（robots 禁止）；无季/集号的特别篇记在 `about` 之外的 extras，不进正片 |
| TMDB | 官方 API v3，免费 key | 分集评分、**中文分集标题与梗概**（`zh-CN`） | 无 key 则跳过；非动画剧集的首选 |
| Bangumi | v0 API，需自定义 UA | 中文作品名/简介、日文分集名、分集**讨论数**、主角 | **v0 API 没有分集评分**（实测），所以 KPI 是讨论热度；中文分集名视条目而定 |
| Wikipedia(en) | MediaWiki API 取 wikitext，解析 `{{Episode list}}` | 英文分集标题 + ShortSummary（写桥接摘要的原料） | 页面名要对（通常 `List of <Title> episodes`） |

页面 KPI 切换只列有数据的源；柱高按该源 min–max 拉伸（否则窄分布看不出差异）。

## 约束

自用、不商用；只抓公开数据、不做登录态。桥接摘要不进脚本——质量不可控，这层留人在环。

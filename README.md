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
| `intro` | **人** | 作品介绍：`cover`（覆盖头图）/ `synopsis`（**无剧透**）/ `characters[{name,name_cn,role,motivation}]`（按 `name` 与 about 合并头像）/ `highlights[]` / `standing` |
| `route[]` | **人** | 有序不重叠：`{kind:"watch", eps:[a,b], why}` 或 `{kind:"bridge", eps:[a,b], title, paragraphs:[]}` |

`route` 允许为空——只有 `episodes` 时页面照样渲染（评分曲线 + 全集列表 + 进度）。`intro` 缺项时页面回退到 `about`（并打"自动抓取"标）。

## 内容更新回路

session 里写好 / 改好 `intro` 与 `route` 片段 → 粘进 json 对应位置 → `py scraper/validate.py` 过 → push → 页面自动生效。**json 就是编辑界面，没有后台。**

## 数据源与已知限制

| 源 | 方式 | 给什么 | 限制 |
|---|---|---|---|
| MAL | Jikan v4，无 key | 分集评分、日/英标题、首播日；作品简介、主角头像 | Jikan 偶发整体 504（MAL 拒连），稍后重跑即可；**不给分集投票数** |
| IMDb | 官方数据集 `title.episode` + `title.ratings`（缓存 7 天，~60 MB） | 分集评分 + 票数 | **不爬页面**（robots 禁止）；无季/集号的特别篇记在 `about` 之外的 extras，不进正片 |
| TMDB | 官方 API v3，免费 key | 分集评分、**中文分集标题与梗概**（`zh-CN`） | 无 key 则跳过；非动画剧集的首选 |
| Bangumi | v0 API，需自定义 UA | 中文作品名/简介、日文分集名、分集**讨论数**、主角 | **v0 API 没有分集评分**（实测），所以 KPI 是讨论热度；中文分集名视条目而定 |
| Wikipedia(en) | MediaWiki API 取 wikitext，解析 `{{Episode list}}` | 英文分集标题 + ShortSummary（写桥接摘要的原料） | 页面名要对（通常 `List of <Title> episodes`） |

页面 KPI 切换只列有数据的源；柱高按该源 min–max 拉伸（否则窄分布看不出差异）。

## 约束

自用、不商用；只抓公开数据、不做登录态。桥接摘要不进脚本——质量不可控，这层留人在环。

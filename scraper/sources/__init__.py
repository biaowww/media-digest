"""
数据源约定：每个模块暴露 `fetch(id, http) -> dict`，返回

{
  "series":   {...},                 # 作品级：标题 / 年份 / 总分 / 封面 / 简介 / 角色
  "episodes": {n: {...}, ...},       # 分集级，key 为从 1 起的顺序集号
}

分集 dict 可含：title_native / title_en / title_cn / aired / synopsis_en / synopsis_zh
以及本源特有的评分字段（score / votes / rating / vote_average / comments ...）。
fetch.py 负责按优先级把各源字段合并进 episodes[]，评分则分源并存、不合并。
"""

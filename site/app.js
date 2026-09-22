/* media-digest · 路线页。纯静态：读 ../shows/<slug>.json，进度存 localStorage。
 * 评分各源并存、页面可切、不合并不加权；热度（讨论数 / 票数）是另一个维度：单独一档 + 🔥 标记。 */
(function () {
  'use strict';
  const $app = document.getElementById('app');
  const params = new URLSearchParams(location.search);
  let slug = params.get('show');

  const h = (tag, attrs, ...kids) => {
    const el = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === 'class') el.className = attrs[k];
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] != null) el.setAttribute(k, attrs[k]);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(kid));
    return el;
  };
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 私密模式等 */ } },
  };
  const S = e => e.sources || {};
  const num = v => Number(v).toLocaleString();

  /* ---------- KPI：单源原始分，只切换不合并 ---------- */
  const SCORE_KPIS = [
    { key: 'imdb', label: 'IMDb', get: e => S(e).imdb && S(e).imdb.rating, votes: e => S(e).imdb && S(e).imdb.votes, fmt: v => v.toFixed(1), scale: '1–10' },
    { key: 'mal', label: 'MAL', get: e => S(e).mal && S(e).mal.score, votes: () => null, fmt: v => v.toFixed(2), scale: '1–5 投票均分' },
    { key: 'tmdb', label: 'TMDB', get: e => S(e).tmdb && S(e).tmdb.vote_average, votes: e => S(e).tmdb && S(e).tmdb.vote_count, fmt: v => v.toFixed(1), scale: '1–10' },
    { key: 'bangumi', label: 'Bangumi', get: e => S(e).bangumi && S(e).bangumi.score, votes: e => S(e).bangumi && S(e).bangumi.votes, fmt: v => v.toFixed(1), scale: '1–10' },
  ];
  // 热度：取覆盖最好的一个计数源，原始数字，不做跨源归一
  const HEAT_SOURCES = [
    { key: 'mal_replies', label: 'MAL 论坛回复' },
    { key: 'bangumi_comments', label: 'Bangumi 讨论' },
    { key: 'imdb_votes', label: 'IMDb 票数' },
  ];
  function buildKpis(eps) {
    const list = SCORE_KPIS.filter(k => eps.some(e => k.get(e) != null));
    const heatSrc = HEAT_SOURCES.find(s => eps.some(e => e.heat && e.heat[s.key] != null));
    let heat = null;
    if (heatSrc) {
      const get = e => (e.heat && e.heat[heatSrc.key] != null) ? e.heat[heatSrc.key] : null;
      const sorted = eps.map(get).filter(v => v != null).sort((a, b) => b - a);
      const cut = sorted[Math.max(0, Math.ceil(sorted.length * 0.1) - 1)];
      heat = { key: 'heat', label: '热度', get, votes: () => null, fmt: v => num(v), scale: heatSrc.label, isHot: e => { const v = get(e); return v != null && sorted.length >= 10 && v >= cut; } };
      list.push(heat);
    }
    return { list, heat };
  }
  // 线性去趋势：扣掉「随集数系统性上浮」（只有看完的人才给后期集打分）
  function detrend(pairs) {
    const xs = pairs.map(p => p[0]), ys = pairs.map(p => p[1]);
    const mx = xs.reduce((a, b) => a + b, 0) / xs.length, my = ys.reduce((a, b) => a + b, 0) / ys.length;
    let n = 0, d = 0; for (let i = 0; i < xs.length; i++) { n += (xs[i] - mx) * (ys[i] - my); d += (xs[i] - mx) ** 2; }
    const b = d ? n / d : 0;
    return new Map(pairs.map(([x, y]) => [x, y - (my + b * (x - mx))]));
  }

  // ---------------- 跨端同步：状态按钮 + 设置面板 ----------------
  function syncButton() {
    const b = h('button', { class: 'sync', onclick: openSyncDialog });
    const paint = () => { const st = MD.Sync.state.status; b.className = 'sync ' + st; b.textContent = (st === 'off' ? '未同步' : MD.Sync.statusText()); b.title = MD.Sync.state.detail || ''; };
    paint(); MD.Sync.onChange(paint);
    return b;
  }
  function openSyncDialog() {
    document.querySelectorAll('dialog.syncdlg').forEach(d => d.remove());
    const on = MD.Sync.configured();
    const tokenIn = h('input', { type: 'password', placeholder: 'github_pat_… 或 ghp_…（只需 gist 权限）', autocomplete: 'off', style: 'width:100%' });
    const msg = h('p', { class: 'small muted' });
    const codeIn = h('textarea', { rows: 3, placeholder: '把另一台设备复制的进度码粘到这里', style: 'width:100%' });
    const btnConnect = h('button', { class: 'btn', onclick: async () => {
      if (!tokenIn.value.trim()) { msg.textContent = '先贴 token'; return; }
      msg.textContent = '连接中…'; btnConnect.disabled = true;
      try { await MD.Sync.connect(tokenIn.value); msg.textContent = '已连接，' + MD.Sync.statusText(); tokenIn.value = ''; setTimeout(() => dlg.close(), 800); }
      catch (e) { msg.textContent = '失败：' + e.message; } finally { btnConnect.disabled = false; }
    } }, on ? '换一个 token' : '连接');
    const dlg = h('dialog', { class: 'syncdlg' },
      h('div', { class: 'sec-hd' }, h('h3', {}, '跨端同步'), h('button', { class: 'fold', onclick: () => dlg.close() }, '关闭')),
      h('p', { class: 'small muted' }, on ? '当前：' + MD.Sync.statusText() + '。进度存在你自己的私密 GitHub Gist 里，每台设备贴一次 token 即可。'
        : '进度存在你自己的私密 GitHub Gist 里。到 GitHub → Settings → Developer settings → Personal access tokens 生成一个只勾 gist 权限的 token，贴到这里；另一台设备贴同一个 token 就同步了。'),
      h('div', { style: 'display:flex;gap:8px;align-items:center;margin:6px 0' }, tokenIn, btnConnect),
      on ? h('div', { style: 'display:flex;gap:8px;margin:4px 0' },
        h('button', { class: 'btn', onclick: async () => { msg.textContent = '同步中…'; await MD.Sync.syncNow(); msg.textContent = MD.Sync.statusText(); } }, '立即同步'),
        h('button', { class: 'btn', onclick: () => { MD.Sync.disconnect(); dlg.close(); } }, '断开（本机进度保留）')) : null,
      msg,
      h('h3', { style: 'margin-top:14px' }, '进度码（不用 token 的手动兜底）'),
      h('div', { style: 'display:flex;gap:8px;margin:6px 0' },
        h('button', { class: 'btn', onclick: async () => { const c = await MD.Code.export(); try { await navigator.clipboard.writeText(c); msg.textContent = '进度码已复制到剪贴板，去另一台设备粘贴导入'; } catch (e) { codeIn.value = c; msg.textContent = '已生成在下方文本框，手动复制'; } } }, '复制本机进度码'),
        h('button', { class: 'btn', onclick: async () => { try { const n = await MD.Code.import(codeIn.value); msg.textContent = `已导入并合并 ${n} 部剧的进度`; codeIn.value = ''; } catch (e) { msg.textContent = '导入失败：' + e.message; } } }, '导入')),
      codeIn);
    document.body.append(dlg); dlg.showModal();
  }

  // 同一 IP 的多个改编版本（meta.series 相同）并成一组：首页一张卡、剧集页顶部 tab。组内按年份排，第一个是默认版本。
  function groupShows(shows) {
    const groups = [], byKey = new Map();
    for (const s of shows || []) {
      const key = s.series || ('__' + s.slug);
      if (!byKey.has(key)) { const g = { key, items: [] }; byKey.set(key, g); groups.push(g); }
      byKey.get(key).items.push(s);
    }
    for (const g of groups) {
      g.items.sort((a, b) => (a.year || 0) - (b.year || 0));
      g.title = (g.items.find(x => x.series_title) || {}).series_title || g.items[0].title_cn || g.items[0].title;
    }
    return groups;
  }
  const vLabel = s => s.version_label || (s.year ? String(s.year) : s.slug);
  function go(newSlug) {  // 站内切换：不整页刷新
    if (!newSlug || newSlug === slug) return;
    history.pushState({}, '', '?show=' + encodeURIComponent(newSlug));
    slug = newSlug; window.scrollTo(0, 0); start();
  }

  // ---------------- 列表页 ----------------
  async function renderList() {
    const r = await fetch('../shows/index.json?t=' + Date.now());  // 绕过 Pages 10 分钟缓存
    const { shows } = await r.json();
    const groups = groupShows(shows);
    $app.replaceChildren(
      h('h1', {}, '追剧路线', h('small', { class: 'muted', style: 'font-size:13px;font-weight:400;margin-left:8px' }, 'media-digest')),
      h('p', { class: 'muted small' }, '把几十集的长剧压成一条路线：必看的集全速看，跳过的集读摘要，进度记在手机里。'),
      h('div', { class: 'list' }, groups.map(g => {
        const s = g.items[0], multi = g.items.length > 1;
        return h('a', { class: 'card', href: '?show=' + encodeURIComponent(s.slug) },
          h('img', { src: s.cover || '', alt: '' }),
          h('div', {}, h('h3', {}, multi ? g.title : (s.title_cn || s.title)),
            multi
              ? h('div', { class: 'chips', style: 'margin:4px 0' }, g.items.map(v => h('span', { class: 'chip' }, vLabel(v), ' · ', String(v.total_eps), v.unit || '集')))
              : h('div', { class: 'muted small' }, [s.title_cn ? s.title : null, s.year, s.total_eps + ' ' + (s.unit || '集')].filter(Boolean).join(' · ')),
            h('div', { class: 'muted small' }, multi ? `${g.items.length} 个版本，页内 tab 切换` : (s.watch_eps ? `路线：看 ${s.watch_eps} ${s.unit || '集'} + ${s.bridges} 段桥接` : '路线尚未编写'))));
      })),
      h('footer', {}, 'media-digest · ', syncButton()),
    );
  }

  // ---------------- 路线页 ----------------
  async function renderShow() {
    const r = await fetch('../shows/' + encodeURIComponent(slug) + '.json?t=' + Date.now());
    if (!r.ok) { $app.replaceChildren(h('p', { class: 'empty' }, `找不到 shows/${slug}.json`)); return; }
    const show = await r.json();
    const meta = show.meta, about = show.about || {}, intro = show.intro || {};
    const eps = show.episodes || [], route = show.route || [];
    const byN = new Map(eps.map(e => [e.n, e]));
    document.title = (meta.title_cn || meta.title) + ' · 追剧路线';
    const U = meta.unit || '集';

    const K_KPI = `md:${slug}:kpi`, K_DET = `md:${slug}:detrend`;
    let done = MD.Progress.done(slug);
    const mark = (n, on) => { MD.Progress.set(slug, n, on); on ? done.add(n) : done.delete(n); };
    let detrendOn = !!store.get(K_DET, false);

    const state = new Map(); // n -> 'watch' | 'bridge'
    const watchEps = [];
    for (const node of route) for (let n = node.eps[0]; n <= node.eps[1]; n++) { state.set(n, node.kind); if (node.kind === 'watch') watchEps.push(n); }
    const bridges = route.filter(x => x.kind === 'bridge');
    const bridgeRead = b => { for (let n = b.eps[0]; n <= b.eps[1]; n++) if (!done.has(n)) return false; return true; };

    const { list: kpis, heat } = buildKpis(eps);
    const preferred = store.get(K_KPI, null) || meta.primary_kpi || 'imdb';
    let kpi = kpis.find(k => k.key === preferred) || kpis[0] || null;
    const hot = e => heat && heat.isHot(e);

    const epTitle = e => e.title_cn || (e.notes && e.notes.title_cn) || e.title_en || e.title_native || `EP ${e.n}`;
    const epSub = e => (e.title_cn && e.title_en && e.title_en !== e.title_cn) ? e.title_en : (e.title_cn || e.title_en) && e.title_native && e.title_native !== e.title_cn ? e.title_native : '';
    const kpiVal = e => { if (!kpi) return null; const v = kpi.get(e); return v == null ? null : kpi.fmt(v); };
    const allScores = e => kpis.filter(k => k.get(e) != null).map(k => `${k.label} ${k.fmt(k.get(e))}${k.votes(e) ? ` (${num(k.votes(e))})` : ''}`).join(' · ');

    // ---- 头部 ----
    const cover = intro.cover || about.cover;
    const scoreChips = Object.entries(about.scores || {}).map(([src, s]) =>
      h('span', { class: 'chip' }, src.toUpperCase() + ' ', h('b', {}, s.score != null ? (Number.isInteger(s.score * 10) ? String(s.score) : Number(s.score).toFixed(1)) : '—'), s.votes ? ` · ${num(s.votes)}` : ''));
    const hero = h('section', { class: 'card hero' },
      cover ? h('img', { src: cover, alt: '' }) : h('div'),
      h('div', {},
        h('h1', {}, meta.title_cn || meta.title),
        h('div', { class: 'sub' }, [meta.title_cn ? meta.title : null, meta.title_native, meta.year, `${meta.total_eps} ${U}`].filter(Boolean).join(' · ')),
        intro.logline ? h('p', { class: 'logline' }, intro.logline) : null,
        h('div', { class: 'chips' }, scoreChips, (about.genres || []).slice(0, 3).map(g => h('span', { class: 'chip' }, g))),
      ));

    // ---- 介绍 ----
    const introKids = [];
    const syn = intro.synopsis || (about.synopsis && (about.synopsis.zh || about.synopsis.en));
    if (syn) introKids.push(h('div', { class: 'intro' },
      h('h3', {}, '剧情简介', h('span', { class: 'tag' }, intro.synopsis ? '无剧透' : '自动抓取')),
      ...String(syn).split(/\n+/).map(p => h('p', {}, p))));
    // 角色头像合并：不要求写法和 MAL 一致。规则：去标点/大小写后，短名的词是长名词的子集即匹配
    // （"Skull Knight" ~ "The Skull Knight"，"Zodd" ~ "Zodd Nosferatu"，"Charlotte" ~ "Charlotte Beatrix Marie Rhody Windam"）；
    // 再兜底：name_cn / role 里提到的英文名。
    const STOP = new Set(['the', 'of', 'von', 'van', 'de', 'la', 'le', 'du', 'da', 'dr', 'mr', 'mrs', 'ms', 'sir', 'lady', 'lord', 'king', 'queen', 'prince', 'princess', 'captain', 'general', 'inspector', 'detective']);
    const toks = s => String(s || '').toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter(t => t && !STOP.has(t));
    const subset = (a, b) => a.length > 0 && a.every(t => b.includes(t));
    const nameMatch = (x, y) => { const a = toks(x), b = toks(y); if (!a.length || !b.length) return false; return subset(a, b) || subset(b, a); };
    const findAuto = c => {
      const pool = about.characters || [];
      return pool.find(a => a.name && c.name && a.name.toLowerCase() === c.name.toLowerCase())
        || pool.find(a => a.name && c.name && nameMatch(a.name, c.name))
        || pool.find(a => a.name && ((c.name_cn || '') + ' ' + (c.role || '')).toLowerCase().includes(a.name.toLowerCase()));
    };
    let chars = (intro.characters || []).map(c => Object.assign({}, findAuto(c) || {}, c));
    if (!chars.length) chars = (about.characters || []).filter(c => c.role === 'Main');
    // 人物：默认只展开前 4 位，其余折叠；name_cn 里的括号别名拆成副行
    const CHARS_SHOWN = 4;
    let charsOpen = false;
    const splitName = s => { const m = String(s || '').match(/^(.*?)[（(](.*)[）)]\s*$/); return m ? [m[1].trim(), m[2].trim()] : [s, null]; };
    const charCard = c => {
      const [cn, alias] = splitName(c.name_cn);
      return h('div', { class: 'char' + (c.image ? '' : ' noimg') },
        c.image ? h('img', { src: c.image, alt: '' }) : null,
        h('div', {}, h('div', { class: 'nm' }, cn || c.name, cn && c.name ? h('small', { class: 'muted' }, ' ' + c.name) : null),
          alias ? h('div', { class: 'role' }, alias) : null,
          c.role ? h('div', { class: 'role' }, c.role) : null,
          c.motivation ? h('div', { class: 'mot' }, c.motivation) : null));
    };
    const charsBox = h('div', {});
    function renderChars() {
      const shown = charsOpen ? chars : chars.slice(0, CHARS_SHOWN);
      charsBox.replaceChildren(
        h('h3', { style: 'margin-bottom:8px' }, '主要人物', h('span', { class: 'muted small', style: 'font-weight:400;margin-left:6px' }, `${chars.length} 位`)),
        h('div', { class: 'chars' }, shown.map(charCard)),
        chars.length > CHARS_SHOWN ? h('button', { class: 'link', style: 'margin-top:8px', onclick: () => { charsOpen = !charsOpen; renderChars(); } }, charsOpen ? '收起' : `展开其余 ${chars.length - CHARS_SHOWN} 位`) : null);
    }
    if (chars.length) { renderChars(); introKids.push(charsBox); }
    if (intro.highlights && intro.highlights.length) introKids.push(h('div', {}, h('h3', { style: 'margin-bottom:6px' }, '亮点'), h('ul', { class: 'hl' }, intro.highlights.map(x => h('li', {}, x)))));
    if (intro.standing) introKids.push(h('div', {}, h('h3', { style: 'margin-bottom:6px' }, '地位'), ...String(intro.standing).split(/\n+/).map(p => h('p', {}, p))));
    // 整块可折叠，状态记在本机（读过一次就不用每次都撑满屏）
    const K_INTRO = `md:${slug}:intro`;
    let introOpen = store.get(K_INTRO, true);
    const introBody = h('div', { class: 'intro-body' }, introKids);
    const introToggle = h('button', { class: 'fold', onclick: () => { introOpen = !introOpen; store.set(K_INTRO, introOpen); introBody.hidden = !introOpen; introToggle.textContent = introOpen ? '收起' : '展开'; } }, introOpen ? '收起' : '展开');
    introBody.hidden = !introOpen;
    const introSec = introKids.length ? h('section', { class: 'card intro-sec' }, h('div', { class: 'sec-hd' }, h('h3', {}, '作品介绍'), introToggle), introBody) : null;

    // ---- 进度 ----
    const progress = h('section', { class: 'card', style: 'margin-top:10px' });
    function renderProgress() {
      const w = watchEps.filter(n => done.has(n)).length, br = bridges.filter(bridgeRead).length;
      const total = route.length ? watchEps.length : eps.length;
      const cur = route.length ? w : [...done].filter(n => byN.has(n)).length;
      progress.replaceChildren(
        h('div', { class: 'progress' },
          h('span', {}, h('span', { class: 'big' }, String(cur)), h('span', { class: 'muted' }, ` / ${total} ${U}已看`)),
          route.length ? h('span', { class: 'muted' }, `桥接已读 ${br} / ${bridges.length}`) : null,
          h('span', { style: 'flex:1' }),
          h('button', { class: 'link', onclick: () => { if (confirm('清空这部剧的进度？（已开同步的话另一端也会清）')) { MD.Progress.reset(slug); done = MD.Progress.done(slug); rerender(); } } }, '重置')),
        h('div', { class: 'bar' }, h('i', { style: `width:${total ? (100 * cur / total) : 0}%` })));
    }

    // ---- 分集梗概（人写、含剧透）----
    // 已看到的集（集号 ≤ 已勾选的最大集号）自动显示；未看的点一下按钮才出——面板同时是比分数用的，翻柱子时不该顺手被剧透。
    const revealed = new Set();
    const KIND = { recurring: '常驻', arc: '阶段', 'one-off': '一次' };
    function notesBlock(e) {
      const n = e.notes;
      if (!n || !(n.summary || (n.new && n.new.length))) return null;
      const maxDone = Math.max(0, ...done);
      const seen = e.n <= maxDone;
      if (!seen && !revealed.has(e.n)) {
        return h('div', { class: 'notes gated' }, h('button', { class: 'btn', onclick: () => { revealed.add(e.n); renderChart(); } }, '显示本集内容（含剧透）'));
      }
      return h('div', { class: 'notes' },
        h('div', { class: 'small muted' }, '本集内容', h('span', { class: 'tag' }, seen ? '已看' : '含剧透')),
        n.summary ? h('p', {}, n.summary) : null,
        n.new && n.new.length ? h('div', { class: 'small' }, h('span', { class: 'muted' }, '新登场：'),
          n.new.map((c, i) => h('span', {}, i ? ' · ' : '', c.name_cn || c.name, c.name_cn && c.name ? h('span', { class: 'muted' }, ` ${c.name}`) : null,
            h('span', { class: 'kind ' + (c.kind || '') }, KIND[c.kind] || c.kind || ''), c.note ? h('span', { class: 'muted' }, `（${c.note}）`) : null))) : null);
    }

    // ---- 图表 ----
    const chartSec = h('section', { class: 'card', style: 'margin-top:10px' });
    let selected = null;
    function renderChart() {
      const tabs = h('div', { class: 'tabs' }, kpis.map(k => h('button', { 'aria-pressed': String(k === kpi), onclick: () => { kpi = k; store.set(K_KPI, k.key); rerender(); } }, k.label)));
      let valOf = e => kpi ? kpi.get(e) : null;
      if (kpi && detrendOn) { const m = detrend(eps.map(e => [e.n, kpi.get(e)]).filter(p => p[1] != null)); valOf = e => m.has(e.n) ? m.get(e.n) : null; }
      const vals = eps.map(valOf).filter(v => v != null);
      const lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 1;
      const bars = eps.map(e => {
        const v = valOf(e);
        const cls = ['b', done.has(e.n) ? 'done' : (state.get(e.n) || ''), v == null ? 'nodata' : '', selected === e.n ? 'sel' : '', hot(e) ? 'hot' : ''].join(' ');
        const hgt = v == null ? 12 : (hi > lo ? 15 + 85 * (v - lo) / (hi - lo) : 60);
        return h('div', { class: cls, style: `height:${hgt}%`, title: `EP ${e.n}`, onclick: () => { selected = selected === e.n ? null : e.n; renderChart(); } });
      });
      const sel = selected != null ? byN.get(selected) : null;
      const detail = sel ? h('div', { class: 'detail' },
        h('span', { class: 't' }, `EP ${sel.n} · ${epTitle(sel)}`), sel.aired ? h('span', { class: 'muted' }, ` · ${sel.aired}`) : null, hot(sel) ? ' 🔥' : null,
        h('div', { class: 'muted small' }, allScores(sel) || '无评分数据'),
        sel.heat ? h('div', { class: 'muted small' }, HEAT_SOURCES.filter(s => sel.heat[s.key] != null).map(s => `${s.label} ${num(sel.heat[s.key])}`).join(' · ')) : null,
        state.get(sel.n) ? h('div', { class: 'small' }, state.get(sel.n) === 'watch' ? '路线：全速看' : '路线：桥接带过') : null,
        notesBlock(sel))
        : h('div', { class: 'detail muted small' }, '点一根柱子看这一集的各源评分与热度');
      const detCb = h('input', { type: 'checkbox', onchange: ev => { detrendOn = ev.target.checked; store.set(K_DET, detrendOn); renderChart(); } }); detCb.checked = detrendOn;
      const axisText = !kpi ? '无评分数据' : detrendOn ? `${kpi.label} · 已去趋势（扣除随集数上浮）` : `${kpi.label}（${kpi.scale}）· 柱高按 ${kpi.fmt(lo)}–${kpi.fmt(hi)} 拉伸`;
      chartSec.replaceChildren(
        tabs,
        h('div', { class: 'axis' }, h('span', {}, axisText), h('span', {}, U === '集' ? `EP 1–${meta.total_eps}` : `1–${meta.total_eps} ${U}`)),
        h('div', { class: 'chart' }, bars),
        h('div', { class: 'legend' }, h('span', {}, h('i', { style: 'background:var(--accent)' }), '全速看'), h('span', {}, h('i', { style: 'background:var(--bridge)' }), '桥接带过'), h('span', {}, h('i', { style: 'background:var(--done)' }), '已看'), route.length ? null : h('span', {}, h('i', { style: 'background:var(--none)' }), '未编路线'),
          heat ? h('span', {}, '🔥 ', heat.scale, ' 前 10%') : null,
          h('label', { class: 'ctl', style: 'margin-left:auto;display:flex;gap:4px;align-items:center' }, detCb, '去趋势')),
        detail);
    }

    // ---- 路线 ----
    const routeSec = h('section', {});
    function epRow(e) {
      const cb = h('input', { type: 'checkbox', onchange: ev => { mark(e.n, ev.target.checked); rerender(); } });
      cb.checked = done.has(e.n);
      const v = kpiVal(e);
      return h('label', { class: 'ep' + (done.has(e.n) ? ' done' : ''), title: allScores(e) }, cb, h('span', { class: 'n' }, String(e.n)),
        h('span', { class: 'ttl' }, epTitle(e), hot(e) ? ' 🔥' : null, epSub(e) ? h('small', {}, epSub(e)) : null), h('span', { class: 'sc' }, v == null ? '' : v));
    }
    const openBridges = new Set();
    function renderRoute() {
      if (!route.length) {
        routeSec.replaceChildren(h('h2', {}, U === '集' ? '全集' : '全部' + U), h('p', { class: 'muted small' }, kpis.length ? '路线尚未编写：先看评分曲线，勾选记录进度。' : '路线尚未编写：勾选记录进度。'),
          h('div', { class: 'card eps' }, eps.map(epRow)));
        return;
      }
      const nodes = route.map((node, i) => {
        const [a, b] = node.eps, k = b - a + 1;
        if (node.kind === 'watch') {
          const rows = []; for (let n = a; n <= b; n++) rows.push(epRow(byN.get(n) || { n, sources: {} }));
          return h('div', { class: 'card node watch' + (node.optional ? ' optional' : '') },
            h('div', { class: 'hd' }, h('span', { class: 'k' }, '看'), h('span', { class: 'rng' }, a === b ? `EP ${a}` : `EP ${a}–${b}`), h('span', { class: 'muted small' }, `${k} ${U}`), node.optional ? h('span', { class: 'tag' }, '可选') : null),
            node.why ? h('p', { class: 'why' }, node.why) : null,
            h('div', { class: 'eps' }, rows));
        }
        const open = openBridges.has(i), read = bridgeRead(node);
        const cb = h('input', { type: 'checkbox', onclick: ev => ev.stopPropagation(), onchange: ev => { for (let n = a; n <= b; n++) mark(n, ev.target.checked); rerender(); } });
        cb.checked = read;
        const body = h('div', { class: 'body' }, node.paragraphs.map(p => h('p', {}, p)));
        body.hidden = !open;
        return h('div', { class: 'card node bridge' + (open ? ' open' : '') + (read ? ' read' : '') },
          h('div', { class: 'hd', onclick: () => { open ? openBridges.delete(i) : openBridges.add(i); renderRoute(); } },
            h('span', { class: 'caret' }, '▶'), h('span', { class: 'k' }, '桥接'), h('span', { class: 'rng' }, a === b ? `EP ${a}` : `EP ${a}–${b}`),
            h('span', { class: 'grow small muted' }, node.title, ` · 跳过 ${k} ${U}`),
            h('label', { class: 'ctl', onclick: ev => ev.stopPropagation() }, cb, '已读')),
          open ? null : h('div', { class: 'spoiler-note' }, '点开阅读摘要（含被跳过集的剧情）'),
          body);
      });
      routeSec.replaceChildren(h('h2', {}, '路线'),
        intro.route_note ? h('p', { class: 'muted small route-note' }, intro.route_note) : null,
        h('div', { class: 'route' }, nodes));
    }

    // ---- 顶部导航：回主页 / 段落锚点 / 切换剧集 ----
    if (introSec) introSec.id = 'intro';
    chartSec.id = 'chart'; routeSec.id = 'route';
    const jump = id => ev => { ev.preventDefault(); const el = document.getElementById(id); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
    const switcher = h('select', { class: 'switch', 'aria-label': '切换剧集', onchange: ev => go(ev.target.value) });
    switcher.hidden = true;
    const vtabs = h('div', { class: 'vtabs' }); vtabs.hidden = true;   // 版本 tab：同系列 ≥2 个版本才出现
    const mySlug = slug;
    fetch('../shows/index.json?t=' + Date.now()).then(r => r.json()).then(({ shows }) => {
      if (mySlug !== slug) return;  // 已切走
      const groups = groupShows(shows);
      const mine = groups.find(g => g.items.some(s => s.slug === slug));
      if (mine && mine.items.length > 1) {
        vtabs.replaceChildren(...mine.items.map(v => h('button', { 'aria-pressed': String(v.slug === slug), onclick: () => go(v.slug) }, vLabel(v), h('small', {}, ` ${v.total_eps}${v.unit || '集'}`))));
        vtabs.hidden = false;
      }
      if (groups.length < 2) return;
      switcher.replaceChildren(...groups.map(g => { const cur = g === mine; const o = h('option', { value: cur ? slug : g.items[0].slug }, g.items.length > 1 ? g.title : (g.items[0].title_cn || g.items[0].title)); o.selected = cur; return o; }));
      switcher.hidden = false;
    }).catch(() => {});
    const topbar = h('nav', { class: 'topbar' },
      h('a', { class: 'back', href: './' }, '← 全部剧集'),
      syncButton(),
      h('div', { class: 'anchors' }, introSec ? h('a', { href: '#intro', onclick: jump('intro') }, '介绍') : null, h('a', { href: '#chart', onclick: jump('chart') }, '评分'), h('a', { href: '#route', onclick: jump('route') }, '路线')),
      switcher);

    function rerender() { renderProgress(); renderChart(); renderRoute(); }
    const mySlugForSync = slug;
    const offSync = MD.Sync.onChange((st, what) => {  // 远端合并进来新进度 → 重画
      if (what !== 'progress' || mySlugForSync !== slug) { if (mySlugForSync !== slug) offSync(); return; }
      done = MD.Progress.done(slug); rerender();
    });
    $app.replaceChildren(topbar, vtabs, hero, introSec, progress, chartSec, routeSec,
      h('footer', {}, h('a', { href: './' }, '全部剧集'), ` · 数据更新 ${meta.updated || '—'}`, ' · 评分各源并列，不合并'));
    rerender();
  }

  function start() { (slug ? renderShow() : renderList()).catch(e => { $app.replaceChildren(h('p', { class: 'empty' }, '加载失败：' + e.message)); console.error(e); }); }
  window.addEventListener('popstate', () => { slug = new URLSearchParams(location.search).get('show'); start(); });
  start();
})();

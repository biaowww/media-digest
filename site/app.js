/* media-digest · 路线页。纯静态：读 ../shows/<slug>.json，进度存 localStorage。 */
(function () {
  'use strict';
  const $app = document.getElementById('app');
  const params = new URLSearchParams(location.search);
  const slug = params.get('show');

  const KPIS = [
    { key: 'mal', label: 'MAL', get: s => s.mal && s.mal.score, fmt: v => v.toFixed(2) },
    { key: 'imdb', label: 'IMDb', get: s => s.imdb && s.imdb.rating, fmt: v => v.toFixed(1), votes: s => s.imdb && s.imdb.votes },
    { key: 'tmdb', label: 'TMDB', get: s => s.tmdb && s.tmdb.vote_average, fmt: v => v.toFixed(1), votes: s => s.tmdb && s.tmdb.vote_count },
    { key: 'bangumi', label: 'Bangumi', get: s => s.bangumi && s.bangumi.score, fmt: v => v.toFixed(1), votes: s => s.bangumi && s.bangumi.votes },
    { key: 'bangumi_comments', label: 'Bangumi 讨论', get: s => s.bangumi && s.bangumi.comments, fmt: v => String(v) },
  ];

  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const h = (tag, attrs, ...kids) => {
    const el = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k === 'class') el.className = attrs[k];
      else if (k === 'html') el.innerHTML = attrs[k];
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

  // ---------------- 列表页 ----------------
  async function renderList() {
    const r = await fetch('../shows/index.json');
    const { shows } = await r.json();
    $app.replaceChildren(
      h('h1', {}, '压缩观看路线'),
      h('p', { class: 'muted small' }, '长剧集，不跳集也不全看：骨架必看 + 桥接摘要。'),
      h('div', { class: 'list' }, shows.map(s => h('a', { class: 'card', href: '?show=' + encodeURIComponent(s.slug) },
        h('img', { src: s.cover || '', alt: '' }),
        h('div', {}, h('h3', {}, s.title_cn || s.title), h('div', { class: 'muted small' }, [s.title_cn ? s.title : null, s.year, s.total_eps + ' 集'].filter(Boolean).join(' · ')),
          h('div', { class: 'muted small' }, s.watch_eps ? `路线：看 ${s.watch_eps} 集 + ${s.bridges} 段桥接` : '路线尚未编写')),
      ))),
      h('footer', {}, 'media-digest'),
    );
  }

  // ---------------- 路线页 ----------------
  async function renderShow() {
    const r = await fetch('../shows/' + encodeURIComponent(slug) + '.json');
    if (!r.ok) { $app.replaceChildren(h('p', { class: 'empty' }, `找不到 shows/${slug}.json`)); return; }
    const show = await r.json();
    const meta = show.meta, about = show.about || {}, intro = show.intro || {};
    const eps = show.episodes || [], route = show.route || [];
    const byN = new Map(eps.map(e => [e.n, e]));
    document.title = (meta.title_cn || meta.title) + ' · 压缩观看路线';

    // 状态
    const K_DONE = `md:${slug}:done`, K_KPI = `md:${slug}:kpi`;
    let done = new Set(store.get(K_DONE, []));
    const saveDone = () => store.set(K_DONE, [...done].sort((a, b) => a - b));

    // 每集属于哪种节点
    const state = new Map(); // n -> 'watch' | 'bridge'
    const watchEps = [];
    for (const node of route) for (let n = node.eps[0]; n <= node.eps[1]; n++) { state.set(n, node.kind); if (node.kind === 'watch') watchEps.push(n); }
    const bridges = route.filter(x => x.kind === 'bridge');
    const bridgeRead = b => { for (let n = b.eps[0]; n <= b.eps[1]; n++) if (!done.has(n)) return false; return true; };

    // 可用 KPI
    const kpis = KPIS.filter(k => eps.some(e => { const v = k.get(e.sources || {}); return v != null; }));
    const preferred = store.get(K_KPI, null) || meta.primary_kpi;
    let kpi = kpis.find(k => k.key === preferred) || kpis[0] || null;

    const epTitle = e => e.title_cn || e.title_en || e.title_native || `EP ${e.n}`;
    const epSub = e => (e.title_cn && e.title_en && e.title_en !== e.title_cn) ? e.title_en : (e.title_cn || e.title_en) && e.title_native && e.title_native !== e.title_cn ? e.title_native : '';
    const kpiVal = e => { if (!kpi) return null; const v = kpi.get(e.sources || {}); return v == null ? null : kpi.fmt(v); };

    // ---- 头部 ----
    const cover = intro.cover || about.cover;
    const scoreChips = Object.entries(about.scores || {}).map(([src, s]) =>
      h('span', { class: 'chip' }, src.toUpperCase() + ' ', h('b', {}, s.score != null ? String(s.score) : '—'), s.votes ? ` · ${Number(s.votes).toLocaleString()}` : ''));
    const hero = h('section', { class: 'card hero' },
      cover ? h('img', { src: cover, alt: '' }) : h('div'),
      h('div', {},
        h('h1', {}, meta.title_cn || meta.title),
        h('div', { class: 'sub' }, [meta.title_cn ? meta.title : null, meta.title_native, meta.year, `${meta.total_eps} 集`].filter(Boolean).join(' · ')),
        h('div', { class: 'chips' }, scoreChips, (about.genres || []).slice(0, 4).map(g => h('span', { class: 'chip' }, g))),
      ));

    // ---- 介绍：无剧透简介 / 人物 / 亮点 / 地位 ----
    const introKids = [];
    const syn = intro.synopsis || (about.synopsis && (about.synopsis.zh || about.synopsis.en));
    if (syn) introKids.push(h('div', { class: 'intro' },
      h('h3', {}, '剧情简介', intro.synopsis ? h('span', { class: 'tag' }, '无剧透') : h('span', { class: 'tag' }, '自动抓取')),
      ...String(syn).split(/\n+/).map(p => h('p', {}, p))));
    // 人物：intro.characters（手写动机）与 about.characters（抓来的头像/角色）按 name 合并
    const autoChars = new Map((about.characters || []).map(c => [c.name.toLowerCase(), c]));
    let chars = (intro.characters || []).map(c => Object.assign({}, autoChars.get((c.name || '').toLowerCase()) || {}, c));
    if (!chars.length) chars = (about.characters || []).filter(c => c.role === 'Main');
    if (chars.length) introKids.push(h('div', {}, h('h3', { style: 'margin-bottom:8px' }, '主要人物'),
      h('div', { class: 'chars' }, chars.map(c => h('div', { class: 'char' + (c.image ? '' : ' noimg') },
        c.image ? h('img', { src: c.image, alt: '' }) : null,
        h('div', {}, h('div', { class: 'nm' }, c.name_cn || c.name, c.name_cn ? h('small', { class: 'muted' }, ' ' + c.name) : null),
          c.role ? h('div', { class: 'role' }, c.role) : null,
          c.motivation ? h('div', { class: 'mot' }, c.motivation) : null))))));
    if (intro.highlights && intro.highlights.length) introKids.push(h('div', {}, h('h3', { style: 'margin-bottom:6px' }, '亮点'), h('ul', { class: 'hl' }, intro.highlights.map(x => h('li', {}, x)))));
    if (intro.standing) introKids.push(h('div', {}, h('h3', { style: 'margin-bottom:6px' }, '地位'), ...String(intro.standing).split(/\n+/).map(p => h('p', {}, p))));
    const introSec = introKids.length ? h('section', { class: 'card', style: 'display:flex;flex-direction:column;gap:14px;margin-top:10px' }, introKids) : null;

    // ---- 进度 ----
    const progress = h('section', { class: 'card', style: 'margin-top:10px' });
    function renderProgress() {
      const w = watchEps.filter(n => done.has(n)).length, br = bridges.filter(bridgeRead).length;
      const total = route.length ? watchEps.length : eps.length;
      const cur = route.length ? w : [...done].filter(n => byN.has(n)).length;
      progress.replaceChildren(
        h('div', { class: 'progress' },
          h('span', {}, h('span', { class: 'big' }, String(cur)), h('span', { class: 'muted' }, ` / ${total} 集已看`)),
          route.length ? h('span', { class: 'muted' }, `桥接已读 ${br} / ${bridges.length}`) : null,
          h('span', { class: 'grow', style: 'flex:1' }),
          h('button', { class: 'link', onclick: () => { if (confirm('清空本机进度？')) { done = new Set(); saveDone(); rerender(); } } }, '重置')),
        h('div', { class: 'bar' }, h('i', { style: `width:${total ? (100 * cur / total) : 0}%` })));
    }

    // ---- 图表 ----
    const chartSec = h('section', { class: 'card', style: 'margin-top:10px' });
    let selected = null;
    function renderChart() {
      const tabs = h('div', { class: 'tabs' }, kpis.map(k => h('button', { 'aria-pressed': String(k === kpi), onclick: () => { kpi = k; store.set(K_KPI, k.key); rerender(); } }, k.label)));
      const vals = kpi ? eps.map(e => kpi.get(e.sources || {})).filter(v => v != null) : [];
      const lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 1;
      const bars = eps.map(e => {
        const v = kpi ? kpi.get(e.sources || {}) : null;
        const cls = ['b', done.has(e.n) ? 'done' : (state.get(e.n) || ''), v == null ? 'nodata' : '', selected === e.n ? 'sel' : ''].join(' ');
        const hgt = v == null ? 12 : (hi > lo ? 15 + 85 * (v - lo) / (hi - lo) : 60);
        return h('div', { class: cls, style: `height:${hgt}%`, title: `EP ${e.n}`, onclick: () => { selected = selected === e.n ? null : e.n; renderChart(); } });
      });
      const sel = selected != null ? byN.get(selected) : null;
      const detail = sel ? h('div', { class: 'detail' },
        h('span', { class: 't' }, `EP ${sel.n} · ${epTitle(sel)}`), sel.aired ? h('span', { class: 'muted' }, ` · ${sel.aired}`) : null,
        h('div', { class: 'muted small' }, KPIS.filter(k => k.get(sel.sources || {}) != null).map(k => `${k.label} ${k.fmt(k.get(sel.sources))}${k.votes && k.votes(sel.sources) ? ` (${Number(k.votes(sel.sources)).toLocaleString()})` : ''}`).join(' · ') || '无评分数据'),
        state.get(sel.n) ? h('div', { class: 'small' }, state.get(sel.n) === 'watch' ? '路线：全速看' : '路线：桥接带过') : null)
        : h('div', { class: 'detail muted small' }, '点一根柱子看这一集的各源评分');
      chartSec.replaceChildren(
        tabs,
        h('div', { class: 'axis' }, h('span', {}, kpi ? `${kpi.label} · 柱高按 ${kpi.fmt(lo)}–${kpi.fmt(hi)} 拉伸` : '无评分数据'), h('span', {}, `EP 1–${meta.total_eps}`)),
        h('div', { class: 'chart' }, bars),
        h('div', { class: 'legend' }, h('span', {}, h('i', { style: 'background:var(--accent)' }), '全速看'), h('span', {}, h('i', { style: 'background:var(--bridge)' }), '桥接带过'), h('span', {}, h('i', { style: 'background:var(--done)' }), '已看'), route.length ? null : h('span', {}, h('i', { style: 'background:var(--none)' }), '未编路线')),
        detail);
    }

    // ---- 路线 ----
    const routeSec = h('section', {});
    function epRow(e) {
      const cb = h('input', { type: 'checkbox', onchange: ev => { ev.target.checked ? done.add(e.n) : done.delete(e.n); saveDone(); rerender(); } });
      cb.checked = done.has(e.n);
      const v = kpiVal(e);
      return h('label', { class: 'ep' + (done.has(e.n) ? ' done' : '') }, cb, h('span', { class: 'n' }, String(e.n)),
        h('span', { class: 'ttl' }, epTitle(e), epSub(e) ? h('small', {}, epSub(e)) : null), h('span', { class: 'sc' }, v == null ? '' : v));
    }
    const openBridges = new Set();
    function renderRoute() {
      if (!route.length) {
        routeSec.replaceChildren(h('h2', {}, '全集'), h('p', { class: 'muted small' }, '路线尚未编写：先看评分曲线，勾选记录进度。'),
          h('div', { class: 'card eps' }, eps.map(epRow)));
        return;
      }
      const nodes = route.map((node, i) => {
        const [a, b] = node.eps, k = b - a + 1;
        if (node.kind === 'watch') {
          const rows = []; for (let n = a; n <= b; n++) rows.push(epRow(byN.get(n) || { n, sources: {} }));
          return h('div', { class: 'card node watch' },
            h('div', { class: 'hd' }, h('span', { class: 'k' }, '看'), h('span', { class: 'rng' }, a === b ? `EP ${a}` : `EP ${a}–${b}`), h('span', { class: 'muted small' }, `${k} 集`)),
            node.why ? h('p', { class: 'why' }, node.why) : null,
            h('div', { class: 'eps' }, rows));
        }
        const open = openBridges.has(i), read = bridgeRead(node);
        const cb = h('input', { type: 'checkbox', onclick: ev => ev.stopPropagation(), onchange: ev => { for (let n = a; n <= b; n++) ev.target.checked ? done.add(n) : done.delete(n); saveDone(); rerender(); } });
        cb.checked = read;
        const body = h('div', { class: 'body' }, node.paragraphs.map(p => h('p', {}, p)));
        body.hidden = !open;
        return h('div', { class: 'card node bridge' + (open ? ' open' : '') + (read ? ' read' : '') },
          h('div', { class: 'hd', onclick: () => { open ? openBridges.delete(i) : openBridges.add(i); renderRoute(); } },
            h('span', { class: 'caret' }, '▶'), h('span', { class: 'k' }, '桥接'), h('span', { class: 'rng' }, a === b ? `EP ${a}` : `EP ${a}–${b}`),
            h('span', { class: 'grow small muted' }, node.title, ` · 跳过 ${k} 集`),
            h('label', { class: 'ctl', onclick: ev => ev.stopPropagation() }, cb, '已读')),
          open ? null : h('div', { class: 'spoiler-note' }, '点开阅读摘要（含被跳过集的剧情）'),
          body);
      });
      routeSec.replaceChildren(h('h2', {}, '路线'), h('div', { class: 'route' }, nodes));
    }

    function rerender() { renderProgress(); renderChart(); renderRoute(); }
    $app.replaceChildren(hero, introSec, progress, chartSec, routeSec,
      h('footer', {}, h('a', { href: './' }, '全部剧集'), ` · 数据更新 ${meta.updated || '—'}`, ' · 评分各源并列，不做综合'));
    rerender();
  }

  (slug ? renderShow() : renderList()).catch(e => { $app.replaceChildren(h('p', { class: 'empty' }, '加载失败：' + e.message)); console.error(e); });
})();

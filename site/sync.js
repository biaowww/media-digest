/* media-digest · 进度存储 + 跨端同步（无后端）
 *
 * 本地：localStorage `md:progress` = { shows: { <slug>: { <n>: { v: 1|0, t: ms } } } }
 *   每集记「已看/未看 + 最后操作时间」，合并时按集取最新一次操作——两台设备各改各的也不会互相覆盖。
 *   （旧格式 `md:<slug>:done` 数组首次加载时自动迁入。）
 *
 * 远端：一个私密 GitHub Gist（文件 media-digest-progress.json），页面直接调 GitHub API 读写。
 *   每台设备贴一次只有 gist 权限的 token（存本机 localStorage `md:sync`）；Gist 由 token 自动发现 / 创建，
 *   不用抄 id。打开页面拉一次并合并；勾选后 2 秒内写回；离线时先记本地，联网后补。
 *
 * 兜底：「进度码」= 全部进度压成一串文本，手动复制到另一台设备导入（同样按时间合并）。
 */
window.MD = (function () {
  'use strict';
  const K_PROG = 'md:progress', K_SYNC = 'md:sync';
  const GIST_FILE = 'media-digest-progress.json';
  const GIST_DESC = 'media-digest progress (auto-managed)';
  const API = 'https://api.github.com';

  const lsGet = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 私密模式等 */ } };

  // ---------------- 本地进度 ----------------
  let prog = lsGet(K_PROG, null) || { shows: {} };
  (function migrate() {  // 旧格式 md:<slug>:done → 新格式
    const old = [];
    for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && /^md:(.+):done$/.test(k)) old.push(k); }
    for (const k of old) {
      const slug = k.slice(3, -5), arr = lsGet(k, []);
      const s = prog.shows[slug] = prog.shows[slug] || {};
      for (const n of arr) if (!s[n]) s[n] = { v: 1, t: 1 };  // 时间戳给最早：迁移来的记录不能压过另一台设备之后的真实操作；两台都迁移时取并集
      try { localStorage.removeItem(k); } catch (e) { /* ignore */ }
    }
    if (old.length) lsSet(K_PROG, prog);
  })();
  const saveProg = () => lsSet(K_PROG, prog);

  const Progress = {
    done(slug) { const s = prog.shows[slug] || {}; return new Set(Object.keys(s).filter(n => s[n].v).map(Number)); },
    set(slug, n, on) {
      const s = prog.shows[slug] = prog.shows[slug] || {};
      s[n] = { v: on ? 1 : 0, t: Date.now() };
      saveProg(); Sync.schedulePush();
    },
    reset(slug) {  // 不删键：记成「未看 @ 现在」，同步后另一端也会跟着清
      const s = prog.shows[slug] || {}, t = Date.now();
      for (const n of Object.keys(s)) s[n] = { v: 0, t };
      saveProg(); Sync.schedulePush();
    },
  };

  // 合并：按集取最新操作。返回 [merged, localChanged, remoteChanged]
  function merge(a, b) {
    const out = { shows: {} };
    let aChanged = false, bChanged = false;
    const slugs = new Set([...Object.keys(a.shows || {}), ...Object.keys(b.shows || {})]);
    for (const slug of slugs) {
      const sa = (a.shows || {})[slug] || {}, sb = (b.shows || {})[slug] || {}, so = out.shows[slug] = {};
      for (const n of new Set([...Object.keys(sa), ...Object.keys(sb)])) {
        const ea = sa[n], eb = sb[n];
        const win = !eb ? ea : !ea ? eb : (eb.t > ea.t ? eb : ea);
        so[n] = win;
        if (!ea || ea.t !== win.t || ea.v !== win.v) aChanged = true;
        if (!eb || eb.t !== win.t || eb.v !== win.v) bChanged = true;
      }
    }
    return [out, aChanged, bChanged];
  }

  // ---------------- Gist 同步 ----------------
  const listeners = new Set();
  const state = { status: lsGet(K_SYNC, {}).token ? 'idle' : 'off', detail: '', lastSync: lsGet(K_SYNC, {}).lastSync || null };
  const cfg = () => lsGet(K_SYNC, {});
  const setCfg = patch => lsSet(K_SYNC, Object.assign(cfg(), patch));
  const emit = () => listeners.forEach(f => { try { f(state); } catch (e) { /* ignore */ } });
  const setStatus = (status, detail) => { state.status = status; state.detail = detail || ''; emit(); };

  async function gh(path, opts) {
    const { token } = cfg();
    const isGet = !opts || !opts.method || opts.method === 'GET';
    // GitHub 给带 token 的响应 Cache-Control: private, max-age=60 —— 浏览器会把 60 秒内的旧列表 / 旧进度喂回来，
    // 第二台设备就「发现不了」刚建的 Gist、拉进度也会拉到陈旧版本再覆盖回去。GET 一律绕缓存。
    const url = API + path + (isGet ? (path.includes('?') ? '&' : '?') + '_=' + Date.now() : '');
    const r = await fetch(url, Object.assign({}, opts, {
      cache: 'no-store',
      headers: Object.assign({ Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' }, (opts && opts.headers) || {}),
    }));
    if (!r.ok) { const e = new Error(`GitHub ${r.status}`); e.status = r.status; throw e; }
    return r.status === 204 ? null : r.json();
  }

  async function ensureGist() {
    const c = cfg();
    if (c.gistId) return c.gistId;
    // 用 token 自动找已有的进度 Gist（另一台设备建的），没有再新建——两台设备不用互相抄 id
    const hits = [];
    for (let page = 1; page <= 5; page++) {
      const list = await gh(`/gists?per_page=100&page=${page}`);
      for (const g of list || []) if (g.files && g.files[GIST_FILE]) hits.push(g);
      if (!list || list.length < 100) break;
    }
    if (hits.length) {
      hits.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
      const keep = hits[0];
      // 多出来的（两台设备同时首连、或历史缓存问题）：内容并进本地，再删掉，保证只剩一个
      for (const extra of hits.slice(1)) {
        try {
          const remote = await pullRemote(extra.id);
          const [merged, localChanged] = merge(prog, remote);
          if (localChanged) { prog = merged; saveProg(); }
          if (extra.description === GIST_DESC && Object.keys(extra.files).length === 1) await gh(`/gists/${extra.id}`, { method: 'DELETE' });
        } catch (e) { /* 删不掉就留着，不影响使用 */ }
      }
      setCfg({ gistId: keep.id });
      return keep.id;
    }
    const created = await gh('/gists', { method: 'POST', body: JSON.stringify({ description: GIST_DESC, public: false, files: { [GIST_FILE]: { content: JSON.stringify({ version: 1, shows: {} }) } } }) });
    setCfg({ gistId: created.id });
    return created.id;
  }

  async function pullRemote(gistId) {
    const g = await gh(`/gists/${gistId}`);
    const f = g.files && g.files[GIST_FILE];
    if (!f) return { version: 1, shows: {} };
    let content = f.content;
    if (f.truncated && f.raw_url) content = await (await fetch(f.raw_url)).text();
    try { return JSON.parse(content || '{}'); } catch (e) { return { version: 1, shows: {} }; }
  }

  let syncing = null, dirty = lsGet(K_SYNC, {}).dirty || false, timer = null;
  async function syncNow() {
    if (!cfg().token) return;
    if (syncing) return syncing;
    syncing = (async () => {
      try {
        setStatus('syncing');
        let id = await ensureGist();
        let remote;
        try { remote = await pullRemote(id); }
        catch (e) { if (e.status !== 404) throw e; setCfg({ gistId: null }); id = await ensureGist(); remote = await pullRemote(id); }  // 记住的 gist 被删了：重新发现 / 新建
        const [merged, localChanged, remoteChanged] = merge(prog, remote);
        if (localChanged) { prog = merged; saveProg(); listeners.forEach(f => { try { f(state, 'progress'); } catch (e) { /* ignore */ } }); }
        if (remoteChanged || dirty) {
          await gh(`/gists/${id}`, { method: 'PATCH', body: JSON.stringify({ files: { [GIST_FILE]: { content: JSON.stringify(Object.assign({ version: 1, updated: new Date().toISOString() }, merged)) } } }) });
        }
        dirty = false; state.lastSync = Date.now(); setCfg({ dirty: false, lastSync: state.lastSync });
        setStatus('ok');
      } catch (e) {
        dirty = true; setCfg({ dirty: true });
        setStatus(e.status === 401 ? 'auth' : (navigator.onLine === false ? 'offline' : 'error'), e.message);
      } finally { syncing = null; }
    })();
    return syncing;
  }

  const Sync = {
    state, onChange(f) { listeners.add(f); return () => listeners.delete(f); },
    configured() { return !!cfg().token; },
    schedulePush() { if (!cfg().token) return; dirty = true; setCfg({ dirty: true }); clearTimeout(timer); timer = setTimeout(syncNow, 2000); },
    syncNow,
    async connect(token) {
      setCfg({ token: token.trim(), gistId: null }); dirty = true;
      await syncNow();
      if (state.status !== 'ok') throw new Error(state.status === 'auth' ? 'token 无效或没有 gist 权限' : (state.detail || '连接失败'));
    },
    disconnect() { lsSet(K_SYNC, {}); dirty = false; setStatus('off'); },
    statusText() {
      const t = state.lastSync ? new Date(state.lastSync).toLocaleString('zh-CN', { hour12: false }).replace(/:\d\d$/, '') : '';
      return { off: '未同步', idle: '待同步', syncing: '同步中…', ok: '已同步 ' + t, offline: '离线，稍后自动同步', auth: 'token 失效', error: '同步失败' }[state.status] || '';
    },
  };
  window.addEventListener('online', () => { if (dirty) syncNow(); });
  if (cfg().token) setTimeout(syncNow, 0);

  // ---------------- 进度码（手动兜底） ----------------
  const b64 = { enc: u8 => btoa(String.fromCharCode(...u8)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''), dec: s => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0)) };
  async function compress(text) {
    if (!window.CompressionStream) return 'J' + b64.enc(new TextEncoder().encode(text));
    const cs = new Blob([text]).stream().pipeThrough(new CompressionStream('deflate-raw'));
    return 'D' + b64.enc(new Uint8Array(await new Response(cs).arrayBuffer()));
  }
  async function decompress(code) {
    const kind = code[0], body = b64.dec(code.slice(1));
    if (kind === 'J') return new TextDecoder().decode(body);
    const ds = new Blob([body]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return await new Response(ds).text();
  }
  const Code = {
    async export() { return 'MD1.' + await compress(JSON.stringify(prog)); },
    async import(code) {
      code = String(code || '').trim();
      if (!code.startsWith('MD1.')) throw new Error('不是有效的进度码');
      const incoming = JSON.parse(await decompress(code.slice(4)));
      const [merged] = merge(prog, incoming);
      prog = merged; saveProg(); Sync.schedulePush();
      listeners.forEach(f => { try { f(state, 'progress'); } catch (e) { /* ignore */ } });
      return Object.keys(incoming.shows || {}).length;
    },
  };

  return { Progress, Sync, Code };
})();

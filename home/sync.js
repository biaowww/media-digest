/* anima-digest · 进度存储 + 跨端同步
 *
 * 本地：localStorage `md:progress` = { shows: { <slug>: { <n>: { v: 1|0, t: ms } } } }
 *   每集记「已看/未看 + 最后操作时间」，合并时按集取最新一次操作——两台设备各改各的也不会互相覆盖。
 *   （旧格式 `md:<slug>:done` 数组首次加载时自动迁入。）
 *
 * 远端：自建服务器 anima-digest.biaotools.site /api/*（server/api.py）。
 *   登录后：打开页面拉一次并合并；勾选后 2 秒内写回；离线时先记本地，联网后补。
 *   未登录：进度只存本机，功能不受影响。注册走邀请制。
 */
window.MD = (function () {
  'use strict';
  const K_PROG = 'md:progress', K_SYNC = 'md:sync';
  const API_BASE = 'https://anima-digest.biaotools.site';
  const API_URL = API_BASE + '/api/progress';

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

  // ---------------- 账号 ----------------
  const listeners = new Set();
  const state = { status: 'local', detail: '', lastSync: lsGet(K_SYNC, {}).lastSync || null };
  const emit = () => listeners.forEach(f => { try { f(state); } catch (e) { /* ignore */ } });
  const setStatus = (status, detail) => { state.status = status; state.detail = detail || ''; emit(); };

  async function api(path, body) {
    const r = await fetch(API_BASE + path, {
      method: body === undefined ? 'GET' : 'POST', cache: 'no-store', credentials: 'include',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(d.error || `server ${r.status}`); e.status = r.status; throw e; }
    return d;
  }

  const Auth = {
    state: { user: null },
    async me() {
      try { Auth.state.user = await api('/api/auth/me'); }
      catch (e) { Auth.state.user = null; }
      if (!Auth.state.user) setStatus('local'); else if (state.status === 'local') setStatus('idle');
      emit();
      return Auth.state.user;
    },
    async login(username, password) {
      Auth.state.user = await api('/api/auth/login', { username, password });
      dirty = true; emit(); await syncNow();
    },
    async register(username, password, invite) {
      Auth.state.user = await api('/api/auth/register', { username, password, invite });
      dirty = true; emit(); await syncNow();
    },
    async logout() {
      try { await api('/api/auth/logout', {}); } catch (e) { /* ignore */ }
      Auth.state.user = null; setStatus('local');
    },
    async createInvite() { return (await api('/api/admin/invites', {})).code; },
    async listInvites() { return (await api('/api/admin/invites')).invites; },
  };

  // ---------------- 服务器同步 ----------------
  let syncing = null, dirty = lsGet(K_SYNC, {}).dirty || false, timer = null;
  async function syncNow() {
    if (!Auth.state.user) { setStatus('local'); return; }
    if (syncing) return syncing;
    syncing = (async () => {
      try {
        setStatus('syncing');
        // 一次 POST 同时完成推和拉：服务端按集合并（与 merge 同规则），返回合并后的全量
        const r = await fetch(API_URL, {
          method: 'POST', cache: 'no-store', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.assign({ version: 1 }, prog)),
        });
        if (r.status === 401) { Auth.state.user = null; setStatus('local', '登录已过期'); return; }
        if (!r.ok) { const e = new Error('server ' + r.status); e.status = r.status; throw e; }
        const remote = await r.json();
        const [merged, localChanged] = merge(prog, remote);
        if (localChanged) { prog = merged; saveProg(); listeners.forEach(f => { try { f(state, 'progress'); } catch (e) { /* ignore */ } }); }
        dirty = false; state.lastSync = Date.now(); lsSet(K_SYNC, { dirty: false, lastSync: state.lastSync });
        setStatus('ok');
      } catch (e) {
        dirty = true; lsSet(K_SYNC, { dirty: true, lastSync: state.lastSync });
        setStatus(navigator.onLine === false ? 'offline' : 'error', e.message);
      } finally { syncing = null; }
    })();
    return syncing;
  }

  const Sync = {
    state, onChange(f) { listeners.add(f); return () => listeners.delete(f); },
    configured() { return !!Auth.state.user; },
    schedulePush() { if (!Auth.state.user) return; dirty = true; lsSet(K_SYNC, { dirty: true, lastSync: state.lastSync }); clearTimeout(timer); timer = setTimeout(syncNow, 2000); },
    syncNow,
    statusText() {
      const t = state.lastSync ? new Date(state.lastSync).toLocaleString('zh-CN', { hour12: false }).replace(/:\d\d$/, '') : '';
      return { off: '未同步', local: '未登录·仅本机', idle: '待同步', syncing: '同步中…', ok: '已同步 ' + t, offline: '离线，稍后自动同步', error: '同步失败' }[state.status] || '';
    },
  };
  window.addEventListener('online', () => { if (dirty) syncNow(); });
  Auth.me().then(u => { if (u) syncNow(); });

  return { Progress, Sync, Auth };
})();

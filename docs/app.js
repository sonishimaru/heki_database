'use strict';

const GROUP_COLORS = {
  appearance: '#b98b5e',
  mind: '#6b8fb5',
  relation: '#a3739c',
  narrative: '#6fa39a',
};

const WEIGHT_LABEL = { core: '骨格', sub: '補強', spice: '一点' };

// 画像が無い／読めないキャラは、分析結果の髪色・目の色から色見本を組み立てて出す。
const HAIR_COLOR = {
  kinpatsu: '#e3bf62', kurokami: '#2f2d35', chapatsu: '#8a5a3b', akagami: '#c2452d',
  aogami: '#4a7fc1', midorigami: '#4e9c6b', 'pinku-gami': '#e18daa', 'murasaki-gami': '#8b6bb5',
  shirogami: '#d3d2da', messhu: '#9b7f68', kasshoku: '#7a5238', irojiro: '#e6ddd4',
};
const EYE_COLOR = {
  akame: '#cc3a4e', aome: '#3f79c9', 'kin-no-me': '#dfa62c', 'midori-no-me': '#3f9b6a',
  'murasaki-no-me': '#8760b8', 'momoiro-no-me': '#e08aa8', 'chairo-no-me': '#8a5f3d',
  heterochromia: '#c9832e',
};

function portrait(c, cls) {
  const hair = c.elements.find((it) => HAIR_COLOR[it.id]);
  const eye = c.elements.find((it) => EYE_COLOR[it.id]);
  const url = (c.image || {}).url;
  const style = `--hair:${HAIR_COLOR[(hair || {}).id] || '#b9b2a4'};--eye:${EYE_COLOR[(eye || {}).id] || '#ffffff'}`;
  return `<span class="portrait ${cls}" style="${style}">
      <span class="portrait-mark">${esc((c.name || '').trim().charAt(0))}</span>
      ${url ? `<img src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ''}
    </span>`;
}
const FORMULA_LABEL = {
  subject: '主体',
  delta: '変化',
  trigger: '発火条件',
  condition: '限定性',
  observer: '観測者',
};

const app = document.getElementById('app');
let DB = null;
let elById = {};
let patById = {};
let charById = {};
let groupById = {};
let axisById = {};

const state = {
  characters: { q: '', group: '', axis: '', element: '', weight: '', pattern: '', tag: '', sort: 'name' },
  patterns: { q: '', group: '', axis: '', element: '', tag: '', sort: 'name' },
  elements: { q: '', group: '', axis: '', tag: '', usage: '', sort: 'kana' },
};

/* ---------------- utilities ---------------- */

const esc = (s) =>
  String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );

const norm = (s) => String(s || '').toLowerCase();

function chip(text, href, cls) {
  const classes = 'chip' + (cls ? ' ' + cls : '');
  return href
    ? `<a class="${classes}" href="${href}">${esc(text)}</a>`
    : `<span class="${classes}">${esc(text)}</span>`;
}

function options(list, current, placeholder) {
  const head = `<option value="">${esc(placeholder)}</option>`;
  return (
    head +
    list
      .map(
        (o) =>
          `<option value="${esc(o.value)}"${o.value === current ? ' selected' : ''}>${esc(o.label)}</option>`
      )
      .join('')
  );
}

function field(label, id, html) {
  return `<div class="field"><label class="field-label" for="${id}">${esc(label)}</label>${html}</div>`;
}

function select(label, id, list, current, placeholder) {
  return field(label, id, `<select id="${id}">${options(list, current, placeholder)}</select>`);
}

function compositionBar(composition) {
  if (!composition || !composition.length) return '';
  const segs = composition
    .map(
      (c) =>
        `<span style="width:${(c.ratio * 100).toFixed(1)}%;background:${GROUP_COLORS[c.group] || '#ccc'}" title="${esc(
          (groupById[c.group] || {}).name || c.group
        )} ${c.count}"></span>`
    )
    .join('');
  return `<div class="bar">${segs}</div>`;
}

function shuffle(list) {
  const out = list.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

function axesOfGroup(groupId) {
  const list = [];
  DB.groups.forEach((g) => {
    if (groupId && g.id !== groupId) return;
    g.axes.forEach((a) => list.push({ value: a.id, label: `${g.name} / ${a.name}` }));
  });
  return list;
}

function tagOptions(items) {
  const counter = new Map();
  items.forEach((it) => (it.tags || []).forEach((t) => counter.set(t, (counter.get(t) || 0) + 1)));
  return [...counter.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'ja'))
    .map(([name, count]) => ({ value: name, label: `${name} (${count})` }));
}

/* ---------------- filter shell ---------------- */

function filterShell(view, blocks, searchPlaceholder) {
  const s = state[view];
  return `
    <section class="filters">
      <div class="search-box">
        <label class="field-label" for="f-q">全文検索</label>
        <input id="f-q" type="search" value="${esc(s.q)}" placeholder="${esc(searchPlaceholder)}" autocomplete="off">
      </div>
      ${blocks}
      <div class="filter-actions"><button class="ghost" id="f-clear">条件をクリア</button></div>
    </section>`;
}

function resultBar(count, unit, sortHtml) {
  return `<div class="result-bar">
      <div class="count">${count.toLocaleString('ja-JP')}<span> ${esc(unit)}</span></div>
      ${sortHtml}
    </div>`;
}

function sortField(view, list) {
  return `<div class="hint">${select('並び順', 'f-sort', list, state[view].sort, '既定')}</div>`;
}

function bindFilters(view, rerender) {
  const s = state[view];
  const q = document.getElementById('f-q');
  if (q) {
    q.addEventListener('input', () => {
      s.q = q.value;
      rerender(true);
    });
  }
  ['group', 'axis', 'element', 'weight', 'pattern', 'tag', 'usage', 'sort'].forEach((key) => {
    const node = document.getElementById('f-' + key);
    if (!node) return;
    node.addEventListener('change', () => {
      s[key] = node.value;
      if (key === 'group') s.axis = '';
      rerender();
    });
  });
  const clear = document.getElementById('f-clear');
  if (clear) {
    clear.addEventListener('click', () => {
      Object.keys(s).forEach((k) => {
        if (k !== 'sort') s[k] = '';
      });
      rerender();
    });
  }
}

function restoreFocus(rerenderedFromSearch) {
  if (!rerenderedFromSearch) return;
  const q = document.getElementById('f-q');
  if (q) {
    q.focus();
    q.setSelectionRange(q.value.length, q.value.length);
  }
}

/* ---------------- characters ---------------- */

function characterHaystack(c) {
  if (c._hay) return c._hay;
  const parts = [c.name, c.kana, c.work, c.author, c.summary];
  c.elements.forEach((it) => {
    const e = elById[it.id];
    if (e) parts.push(e.name, e.kana, ...(e.aliases || []), it.note);
  });
  c.patterns.forEach((pid) => {
    const p = patById[pid];
    if (p) parts.push(p.name, p.kana, ...(p.aliases || []));
  });
  c._hay = norm(parts.join(' '));
  return c._hay;
}

function filterCharacters() {
  const s = state.characters;
  const q = norm(s.q).trim();
  let list = DB.characters.filter((c) => {
    if (q && !characterHaystack(c).includes(q)) return false;
    if (s.element && !c.elements.some((it) => it.id === s.element)) return false;
    if (s.weight && !c.elements.some((it) => it.weight === s.weight && (!s.element || it.id === s.element)))
      return false;
    if (s.axis && !c.elements.some((it) => elById[it.id].axis === s.axis)) return false;
    if (s.group && !c.elements.some((it) => elById[it.id].group === s.group)) return false;
    if (s.pattern && !c.patterns.includes(s.pattern)) return false;
    if (s.tag && !c.patterns.some((pid) => (patById[pid].tags || []).includes(s.tag))) return false;
    return true;
  });
  const sorters = {
    name: (a, b) => a.kana.localeCompare(b.kana, 'ja'),
    elements: (a, b) => b.elements.length - a.elements.length,
    year: (a, b) => (a.year || 9999) - (b.year || 9999),
  };
  if (s.sort === 'random') list = shuffle(list);
  else list.sort(sorters[s.sort] || sorters.name);
  return list;
}

function characterCard(c) {
  const chips = c.elements
    .filter((it) => it.weight === 'core')
    .slice(0, 4)
    .map((it) => chip(elById[it.id].name, null, 'core'))
    .concat(c.patterns.slice(0, 2).map((pid) => chip(patById[pid].name, null, 'pattern')));
  const rest = c.elements.length - Math.min(4, c.elements.filter((it) => it.weight === 'core').length);
  if (rest > 0) chips.push(chip('他 ' + rest, null, 'more'));
  return `<a class="card" href="#/c/${c.id}">
      <div class="card-head">
        ${portrait(c, 'sm')}
        <div class="card-headtext">
          <div class="card-kicker">${esc(c.work)}${c.year ? ' ・ ' + c.year : ''}</div>
          <div class="card-title">${esc(c.name)}</div>
          <div class="card-kana">${esc(c.kana)}</div>
        </div>
      </div>
      <p class="card-summary">${esc(c.summary)}</p>
      ${compositionBar(c.composition)}
      <div class="chips">${chips.join('')}</div>
    </a>`;
}

function renderCharacters(fromSearch) {
  const s = state.characters;
  const blocks = `
    <div class="filter-group">
      <h2>構成要素で絞る</h2>
      <div class="filter-row">
        ${select('大分類', 'f-group', DB.groups.map((g) => ({ value: g.id, label: `${g.name} (${g.axes.reduce((n, a) => n + a.count, 0)})` })), s.group, 'すべて')}
        ${select('軸', 'f-axis', axesOfGroup(s.group), s.axis, 'すべて')}
        ${select('要素', 'f-element', DB.elements.filter((e) => (!s.group || e.group === s.group) && (!s.axis || e.axis === s.axis)).map((e) => ({ value: e.id, label: e.name })), s.element, 'すべて')}
        ${select('比重', 'f-weight', [{ value: 'core', label: '骨格' }, { value: 'sub', label: '補強' }, { value: 'spice', label: '一点' }], s.weight, 'すべて')}
      </div>
    </div>
    <div class="filter-group">
      <h2>性癖で絞る</h2>
      <div class="filter-row">
        ${select('性癖パターン', 'f-pattern', DB.patterns.map((p) => ({ value: p.id, label: p.name })), s.pattern, 'すべて')}
        ${select('性癖タグ', 'f-tag', tagOptions(DB.patterns), s.tag, 'すべて')}
      </div>
    </div>`;

  const list = filterCharacters();
  app.innerHTML =
    filterShell('characters', blocks, '名前・作品・要素・性癖など') +
    resultBar(
      list.length,
      '名',
      sortField('characters', [
        { value: 'name', label: '五十音' },
        { value: 'elements', label: '要素数の多い順' },
        { value: 'year', label: '成立年の古い順' },
        { value: 'random', label: 'ランダム' },
      ])
    ) +
    (list.length
      ? `<div class="grid">${list.map(characterCard).join('')}</div>`
      : `<p class="empty">条件に合うキャラクターがいません。</p>`);
  bindFilters('characters', renderCharacters);
  restoreFocus(fromSearch);
}

/* ---------------- patterns ---------------- */

function filterPatterns() {
  const s = state.patterns;
  const q = norm(s.q).trim();
  let list = DB.patterns.filter((p) => {
    if (q) {
      const hay = norm(
        [p.name, p.kana, ...(p.aliases || []), p.summary, ...Object.values(p.formula), p.breaks_when, ...(p.tags || [])].join(' ')
      );
      if (!hay.includes(q)) return false;
    }
    if (s.group && p.group !== s.group) return false;
    if (s.axis && p.core_axis !== s.axis) return false;
    if (s.element && !p.requires.includes(s.element) && !p.intensifiers.includes(s.element)) return false;
    if (s.tag && !(p.tags || []).includes(s.tag)) return false;
    return true;
  });
  const sorters = {
    kana: (a, b) => a.kana.localeCompare(b.kana, 'ja'),
    characters: (a, b) => b.characters.length - a.characters.length,
    axis: (a, b) => a.core_axis.localeCompare(b.core_axis),
  };
  if (s.sort === 'random') list = shuffle(list);
  else list.sort(sorters[s.sort] || sorters.kana);
  return list;
}

function patternCard(p) {
  return `<a class="card" href="#/p/${p.id}">
      <div class="card-kicker">${esc(p.group_name)} / ${esc(p.core_axis_name)}</div>
      <div class="card-title">${esc(p.name)}</div>
      <div class="card-kana">${esc(p.kana)}</div>
      <p class="card-summary">${esc(p.summary)}</p>
      <table class="kv formula" style="margin-bottom:12px">
        <tr><th>主体</th><td>${esc(p.formula.subject)}</td></tr>
        <tr><th>変化</th><td>${esc(p.formula.delta)}</td></tr>
      </table>
      <div class="chips">${p.requires
        .map((id) => chip(elById[id].name, null, 'core'))
        .concat((p.tags || []).map((t) => chip(t)))
        .join('')}</div>
    </a>`;
}

function renderPatterns(fromSearch) {
  const s = state.patterns;
  const blocks = `
    <div class="filter-group">
      <h2>成分で絞る</h2>
      <div class="filter-row">
        ${select('主成分の大分類', 'f-group', DB.groups.map((g) => ({ value: g.id, label: g.name })), s.group, 'すべて')}
        ${select('主成分の軸', 'f-axis', axesOfGroup(s.group), s.axis, 'すべて')}
        ${select('使われている要素', 'f-element', DB.elements.map((e) => ({ value: e.id, label: e.name })), s.element, 'すべて')}
        ${select('タグ', 'f-tag', tagOptions(DB.patterns), s.tag, 'すべて')}
      </div>
    </div>`;
  const list = filterPatterns();
  app.innerHTML =
    filterShell('patterns', blocks, '性癖名・主体・変化・条件など') +
    resultBar(
      list.length,
      '性癖',
      sortField('patterns', [
        { value: 'kana', label: '五十音' },
        { value: 'characters', label: '実例の多い順' },
        { value: 'axis', label: '軸順' },
        { value: 'random', label: 'ランダム' },
      ])
    ) +
    (list.length
      ? `<div class="grid">${list.map(patternCard).join('')}</div>`
      : `<p class="empty">条件に合う性癖がありません。</p>`);
  bindFilters('patterns', renderPatterns);
  restoreFocus(fromSearch);
}

/* ---------------- elements ---------------- */

function filterElements() {
  const s = state.elements;
  const q = norm(s.q).trim();
  let list = DB.elements.filter((e) => {
    if (q) {
      const hay = norm([e.name, e.kana, ...(e.aliases || []), e.summary, e.description, e.effect, ...(e.tags || [])].join(' '));
      if (!hay.includes(q)) return false;
    }
    if (s.group && e.group !== s.group) return false;
    if (s.axis && e.axis !== s.axis) return false;
    if (s.tag && !(e.tags || []).includes(s.tag)) return false;
    if (s.usage === 'used' && !e.characters.length) return false;
    if (s.usage === 'unused' && e.characters.length) return false;
    if (s.usage === 'pattern' && !e.patterns.length) return false;
    return true;
  });
  const sorters = {
    kana: (a, b) => a.kana.localeCompare(b.kana, 'ja'),
    axis: (a, b) => a.axis.localeCompare(b.axis) || a.kana.localeCompare(b.kana, 'ja'),
    characters: (a, b) => b.characters.length - a.characters.length,
    patterns: (a, b) => b.patterns.length - a.patterns.length,
  };
  if (s.sort === 'random') list = shuffle(list);
  else list.sort(sorters[s.sort] || sorters.kana);
  return list;
}

function elementCard(e) {
  const chips = (e.tags || []).map((t) => chip(t));
  if (e.characters.length) chips.push(chip(`実例 ${e.characters.length}`, null, 'more'));
  if (e.patterns.length) chips.push(chip(`性癖 ${e.patterns.length}`, null, 'pattern'));
  return `<a class="card" href="#/e/${e.id}">
      <div class="card-kicker">${esc(e.group_name)} / ${esc(e.axis_name)}</div>
      <div class="card-title">${esc(e.name)}</div>
      <div class="card-kana">${esc(e.kana)}${e.aliases.length ? '　' + esc(e.aliases.join('・')) : ''}</div>
      <p class="card-summary">${esc(e.summary)}</p>
      <div class="chips">${chips.join('')}</div>
    </a>`;
}

function renderElements(fromSearch) {
  const s = state.elements;
  const blocks = `
    <div class="filter-group">
      <h2>軸で絞る</h2>
      <div class="filter-row">
        ${select('大分類', 'f-group', DB.groups.map((g) => ({ value: g.id, label: `${g.name} (${g.axes.reduce((n, a) => n + a.count, 0)})` })), s.group, 'すべて')}
        ${select('軸', 'f-axis', axesOfGroup(s.group), s.axis, 'すべて')}
        ${select('タグ', 'f-tag', tagOptions(DB.elements), s.tag, 'すべて')}
        ${select('収録状況', 'f-usage', [
          { value: 'used', label: '実例のあるもの' },
          { value: 'unused', label: '実例のないもの' },
          { value: 'pattern', label: '性癖に使われているもの' },
        ], s.usage, 'すべて')}
      </div>
    </div>`;
  const list = filterElements();
  app.innerHTML =
    filterShell('elements', blocks, '見出し語・別名・説明など') +
    resultBar(
      list.length,
      '要素',
      sortField('elements', [
        { value: 'kana', label: '五十音' },
        { value: 'axis', label: '軸順' },
        { value: 'characters', label: '実例の多い順' },
        { value: 'patterns', label: '性癖での使用が多い順' },
        { value: 'random', label: 'ランダム' },
      ])
    ) +
    (list.length
      ? `<div class="grid">${list.map(elementCard).join('')}</div>`
      : `<p class="empty">条件に合う要素がありません。</p>`);
  bindFilters('elements', renderElements);
  restoreFocus(fromSearch);
}

/* ---------------- details ---------------- */

function detailHead(title, kana, backHref, backLabel) {
  return `<div class="detail-head">
      <h1>${esc(title)}</h1>
      ${kana ? `<span class="kana">${esc(kana)}</span>` : ''}
      <a class="back" href="${backHref}">← ${esc(backLabel)}</a>
    </div>`;
}

function renderCharacterDetail(id) {
  const c = charById[id];
  if (!c) return renderNotFound();
  const byGroup = new Map();
  c.elements.forEach((it) => {
    const e = elById[it.id];
    if (!byGroup.has(e.group)) byGroup.set(e.group, []);
    byGroup.get(e.group).push({ it, e });
  });

  const groupsHtml = [...byGroup.entries()]
    .sort((a, b) => b[1].length - a[1].length)
    .map(
      ([gid, rows]) => `<div class="axis-block">
        <h3><span class="dot" style="background:${GROUP_COLORS[gid]}"></span>${esc(groupById[gid].name)}</h3>
        ${rows
          .map(
            ({ it, e }) => `<div class="elem-row">
              <span class="w ${it.weight}">${esc(WEIGHT_LABEL[it.weight] || it.weight)}</span>
              <a class="name" href="#/e/${e.id}">${esc(e.name)}</a>
              <span class="note">${esc(it.note || e.summary)}</span>
            </div>`
          )
          .join('')}
      </div>`
    )
    .join('');

  const related = DB.characters
    .filter((o) => o.id !== c.id)
    .map((o) => {
      const shared = o.elements.filter((it) => c.elements.some((x) => x.id === it.id));
      return { o, shared };
    })
    .filter((r) => r.shared.length >= 2)
    .sort((a, b) => b.shared.length - a.shared.length)
    .slice(0, 6);

  const image = c.image || {};
  const credit = image.url
    ? `<p class="portrait-credit">画像: ${
        image.page
          ? `<a href="${esc(image.page)}" target="_blank" rel="noopener noreferrer">${esc(image.credit || '出典')}</a>`
          : esc(image.credit || '出典')
      }（参照。当サイトは画像を保持していません）</p>`
    : '<p class="portrait-credit">画像なし。髪色・目の色は分析結果から。</p>';

  app.innerHTML = `<section class="detail">
    ${detailHead(c.name, c.kana, '#/', 'キャラ名鑑へ戻る')}
    <div class="lede-row">
      <div class="portrait-box">
        ${portrait(c, 'lg')}
        ${credit}
      </div>
      <p class="lede">${esc(c.summary)}</p>
    </div>
    <div class="cols">
      <div>
        <div class="block">
          <h2>構成要素 ${c.elements.length}</h2>
          ${groupsHtml}
        </div>
      </div>
      <div>
        <div class="block">
          <h2>成立している性癖</h2>
          ${
            c.patterns.length
              ? c.patterns
                  .map((pid) => {
                    const p = patById[pid];
                    return `<a class="list-link" href="#/p/${p.id}"><b>${esc(p.name)}</b><small>${esc(p.summary)}</small></a>`;
                  })
                  .join('')
              : '<p class="empty">登録されていません。</p>'
          }
        </div>
        <div class="block">
          <h2>出典</h2>
          <table class="kv">
            <tr><th>作品</th><td>${esc(c.work)}</td></tr>
            ${c.year ? `<tr><th>成立</th><td>${esc(c.year)} 年頃</td></tr>` : ''}
            ${c.author ? `<tr><th>作者</th><td>${esc(c.author)}</td></tr>` : ''}
            ${
              c.analysis && c.analysis.method
                ? `<tr><th>分析</th><td>${esc(c.analysis.method)}${
                    c.analysis.model ? `・${esc(c.analysis.model)}` : ''
                  }${c.analysis.frames ? `・${esc(c.analysis.frames)}枚` : ''}${
                    c.analysis.cuts ? `／${esc(c.analysis.cuts)}カット` : ''
                  }</td></tr>`
                : ''
            }
          </table>
        </div>
        <div class="block">
          <h2>構成比</h2>
          ${compositionBar(c.composition)}
          <div class="legend">${c.composition
            .map(
              (x) =>
                `<span><i class="dot" style="background:${GROUP_COLORS[x.group]}"></i>${esc(
                  groupById[x.group].name
                )} ${x.count}</span>`
            )
            .join('')}</div>
        </div>
        <div class="block">
          <h2>要素が重なる人物</h2>
          ${
            related.length
              ? related
                  .map(
                    (r) =>
                      `<a class="list-link" href="#/c/${r.o.id}"><b>${esc(r.o.name)}</b><small>共通 ${
                        r.shared.length
                      }：${esc(r.shared.map((s) => elById[s.id].name).join('・'))}</small></a>`
                  )
                  .join('')
              : '<p class="empty">2 要素以上重なる人物はいません。</p>'
          }
        </div>
      </div>
    </div>
  </section>`;
}

function renderPatternDetail(id) {
  const p = patById[id];
  if (!p) return renderNotFound();
  const candidates = DB.characters
    .filter(
      (c) =>
        !p.characters.includes(c.id) &&
        p.requires.length > 0 &&
        p.requires.every((eid) => c.elements.some((it) => it.id === eid))
    )
    .sort(
      (a, b) =>
        p.intensifiers.filter((eid) => b.elements.some((it) => it.id === eid)).length -
        p.intensifiers.filter((eid) => a.elements.some((it) => it.id === eid)).length
    );
  const elemLinks = (ids) =>
    ids.length
      ? `<div class="chips">${ids.map((eid) => chip(elById[eid].name, `#/e/${eid}`, 'core')).join('')}</div>`
      : '<p class="empty">なし</p>';

  app.innerHTML = `<section class="detail">
    ${detailHead(p.name, p.kana, '#/patterns', '性癖パターンへ戻る')}
    <p class="lede">${esc(p.summary)}</p>
    <div class="cols">
      <div>
        <div class="block">
          <h2>成立の文法</h2>
          <table class="kv formula">
            ${Object.keys(FORMULA_LABEL)
              .map((k) => `<tr><th>${esc(FORMULA_LABEL[k])}</th><td>${esc(p.formula[k])}</td></tr>`)
              .join('')}
          </table>
        </div>
        <div class="block">
          <h2>成立に必要な要素</h2>
          ${elemLinks(p.requires)}
        </div>
        <div class="block">
          <h2>強化する要素</h2>
          ${elemLinks(p.intensifiers)}
        </div>
        <div class="block">
          <h2>壊れる条件</h2>
          <p>${esc(p.breaks_when)}</p>
        </div>
      </div>
      <div>
        <div class="block">
          <h2>分類</h2>
          <table class="kv">
            <tr><th>主成分</th><td>${esc(p.group_name)} / ${esc(p.core_axis_name)}</td></tr>
            ${p.aliases.length ? `<tr><th>別名</th><td>${esc(p.aliases.join('・'))}</td></tr>` : ''}
            ${p.tags.length ? `<tr><th>タグ</th><td>${esc(p.tags.join('・'))}</td></tr>` : ''}
          </table>
        </div>
        <div class="block">
          <h2>実例</h2>
          ${
            p.characters.length
              ? p.characters
                  .map((cid) => {
                    const c = charById[cid];
                    return `<a class="list-link" href="#/c/${c.id}"><b>${esc(c.name)}</b><small>${esc(c.work)}</small></a>`;
                  })
                  .join('')
              : '<p class="empty">まだ登録されていません。</p>'
          }
        </div>
        <div class="block">
          <h2>要素上は成立しうる人物</h2>
          ${
            candidates.length
              ? candidates
                  .map((c) => {
                    const hit = p.intensifiers.filter((eid) => c.elements.some((it) => it.id === eid)).length;
                    return `<a class="list-link" href="#/c/${c.id}"><b>${esc(c.name)}</b><small>必要要素を充足${
                      hit ? `・強化要素 ${hit}` : ''
                    }</small></a>`;
                  })
                  .join('')
              : '<p class="empty">必要要素をすべて満たす人物はいません。</p>'
          }
        </div>
        <div class="block">
          <h2>近い性癖</h2>
          ${
            p.related.length
              ? p.related
                  .map((rid) => {
                    const r = patById[rid];
                    return `<a class="list-link" href="#/p/${r.id}"><b>${esc(r.name)}</b><small>${esc(r.summary)}</small></a>`;
                  })
                  .join('')
              : '<p class="empty">なし</p>'
          }
        </div>
      </div>
    </div>
  </section>`;
}

function renderElementDetail(id) {
  const e = elById[id];
  if (!e) return renderNotFound();
  const linkChips = (ids) =>
    ids.length
      ? `<div class="chips">${ids.map((x) => chip(elById[x].name, `#/e/${x}`)).join('')}</div>`
      : '<p class="empty">なし</p>';

  const patternRows = e.patterns
    .map((x) => {
      const p = patById[x.id];
      return `<a class="list-link" href="#/p/${p.id}"><b>${esc(p.name)}</b><small>${
        x.role === 'requires' ? '成立に必要' : '強化要素'
      }：${esc(p.summary)}</small></a>`;
    })
    .join('');

  app.innerHTML = `<section class="detail">
    ${detailHead(e.name, e.kana, '#/elements', '要素辞典へ戻る')}
    <p class="lede">${esc(e.summary)}</p>
    <div class="cols">
      <div>
        <div class="block">
          <h2>解説</h2>
          <p>${esc(e.description)}</p>
        </div>
        <div class="block">
          <h2>どう効くか</h2>
          <p>${esc(e.effect)}</p>
        </div>
        <div class="block">
          <h2>相性のいい要素</h2>
          ${linkChips(e.pairs_with)}
        </div>
        <div class="block">
          <h2>対比・落差を作る要素</h2>
          ${linkChips(e.contrasts_with)}
        </div>
      </div>
      <div>
        <div class="block">
          <h2>分類</h2>
          <table class="kv">
            <tr><th>軸</th><td>${esc(e.group_name)} / ${esc(e.axis_name)}</td></tr>
            ${e.aliases.length ? `<tr><th>別名</th><td>${esc(e.aliases.join('・'))}</td></tr>` : ''}
            ${e.tags.length ? `<tr><th>タグ</th><td>${esc(e.tags.join('・'))}</td></tr>` : ''}
          </table>
        </div>
        <div class="block">
          <h2>この要素を使う性癖</h2>
          ${patternRows || '<p class="empty">未登録です。</p>'}
        </div>
        <div class="block">
          <h2>この要素を持つ人物</h2>
          ${
            e.characters.length
              ? e.characters
                  .map((x) => {
                    const c = charById[x.id];
                    return `<a class="list-link" href="#/c/${c.id}"><b>${esc(c.name)}</b><small>${esc(
                      WEIGHT_LABEL[x.weight] || x.weight
                    )}・${esc(c.work)}</small></a>`;
                  })
                  .join('')
              : '<p class="empty">未登録です。</p>'
          }
        </div>
      </div>
    </div>
  </section>`;
}

function renderNotFound() {
  app.innerHTML = `<section class="detail">${detailHead('見つかりません', '', '#/', 'トップへ')}
    <p class="empty">その項目は登録されていません。</p></section>`;
}


/* ---------------- dashboard ---------------- */

const LANE_LABEL = {
  danbooru: '外見（Danbooru）',
  'wd-tagger': '外見（画像）',
  gemini: '資料・分類',
  speech: '台詞',
  observe: '映像',
};

function characterLanes(c) {
  const lanes = new Set();
  c.elements.forEach((it) => { if (it.src) lanes.add(it.src); });
  const method = ((c.analysis || {}).method || '');
  method.split('+').forEach((m) => {
    if (m && m !== 'auto') lanes.add(m);
  });
  return [...lanes];
}

function characterGaps(c) {
  const gaps = [];
  if (!c.summary || c.summary === '（要記入）') gaps.push('summary未記入');
  const hasVisual = c.elements.some((it) => (elById[it.id] || {}).group === 'appearance');
  const hasNonVisual = c.elements.some((it) => (elById[it.id] || {}).group !== 'appearance');
  if (!hasVisual) gaps.push('外見なし');
  if (!hasNonVisual) gaps.push('非外見なし');
  if (!c.patterns.length) gaps.push('性癖未設定');
  return gaps;
}

function weightCounts(c) {
  const n = { core: 0, sub: 0, spice: 0 };
  c.elements.forEach((it) => { n[it.weight] = (n[it.weight] || 0) + 1; });
  return n;
}

function tile(num, unit, label) {
  return `<div class="tile"><div class="num">${esc(num)}<small> ${esc(unit)}</small></div><div class="lbl">${esc(label)}</div></div>`;
}

function statusBadge(c) {
  return c.curated
    ? '<span class="badge ok">レビュー済み</span>'
    : '<span class="badge warn">自動下書き</span>';
}

function renderDashboard() {
  const chars = DB.characters;
  const curated = chars.filter((c) => c.curated);
  const drafts = chars.filter((c) => !c.curated);
  const inDb = new Set(chars.map((c) => c.id));
  const waiting = (DB.queue || []).filter((q) => !inDb.has(q.id));
  const patternsWithCases = DB.patterns.filter((p) => p.characters.length).length;
  const elementsWithCases = DB.elements.filter((e) => e.characters.length).length;

  const rows = chars
    .slice()
    .sort((a, b) => {
      const da = (a.analysis || {}).date || '';
      const db_ = (b.analysis || {}).date || '';
      if (da !== db_) return db_.localeCompare(da);
      return a.kana.localeCompare(b.kana, 'ja');
    })
    .map((c) => {
      const lanes = characterLanes(c);
      const laneHtml = lanes.length
        ? lanes.map((l) => `<span class="badge lane">${esc(LANE_LABEL[l] || l)}</span>`).join(' ')
        : '<span class="badge lane">手作業</span>';
      const n = weightCounts(c);
      const gaps = characterGaps(c);
      const date = (c.analysis || {}).date || '—';
      return `<tr>
          <td><a href="#/c/${c.id}">${esc(c.name)}</a><div class="sub-line">${esc(c.work)}</div></td>
          <td>${statusBadge(c)}</td>
          <td>${laneHtml}</td>
          <td>${esc(date)}</td>
          <td>${c.elements.length}<div class="sub-line">骨格${n.core}・補強${n.sub}・一点${n.spice}</div></td>
          <td>${c.patterns.length || '—'}</td>
          <td>${gaps.length ? `<span class="gap-note">${esc(gaps.join('・'))}</span>` : '<span class="badge ok">完備</span>'}</td>
        </tr>`;
    })
    .join('');

  const waitingRows = waiting
    .map(
      (q) => `<tr>
        <td>${esc(q.name)}<div class="sub-line">${esc(q.work)}</div></td>
        <td><span class="badge wait">待機中</span></td>
        <td>${q.lanes.map((l) => `<span class="badge lane">${esc(l)}</span>`).join(' ')}</td>
        <td colspan="4"><span class="sub-line">次回の自動実行（毎日 05:00 JST）で取り込まれる</span></td>
      </tr>`
    )
    .join('');

  const groupCoverage = DB.groups
    .map((g) => {
      const total = g.axes.reduce((n_, a) => n_ + a.count, 0);
      const used = DB.elements.filter((e) => e.group === g.id && e.characters.length).length;
      const pct = total ? Math.round((used / total) * 100) : 0;
      return `<div class="cov-row">
          <span class="cov-label">${esc(g.name)}</span>
          <span class="cov-track"><span class="cov-fill" style="width:${pct}%;background:${GROUP_COLORS[g.id]}"></span></span>
          <span class="cov-num">${used} / ${total}</span>
        </div>`;
    })
    .join('');

  app.innerHTML = `
    <div class="tiles">
      ${tile(chars.length, '名', '収録キャラクター')}
      ${tile(curated.length, '名', 'レビュー済み（手書き）')}
      ${tile(drafts.length, '名', '自動下書き（未レビュー）')}
      ${tile(waiting.length, '件', 'キュー待機中')}
      ${tile(`${patternsWithCases} / ${DB.patterns.length}`, '', '実例のある性癖')}
      ${tile(`${elementsWithCases} / ${DB.elements.length}`, '', '実例のある要素')}
    </div>

    <section class="dash-section">
      <h2>キャラクター別の分析状況</h2>
      <p class="hint">レーン = どの収集ラインの証拠で構成されているか。自動下書きは data/characters_auto.yaml、レビュー済みは data/characters.yaml。</p>
      <div class="table-scroll">
        <table class="status">
          <thead><tr><th>キャラクター</th><th>状態</th><th>レーン</th><th>最終分析</th><th>要素</th><th>性癖</th><th>欠け</th></tr></thead>
          <tbody>${waitingRows}${rows}</tbody>
        </table>
      </div>
    </section>

    <section class="dash-section">
      <h2>要素辞典のカバレッジ</h2>
      <p class="hint">各分類の見出し語のうち、実例（キャラクター）が付いている割合。</p>
      <div class="block">${groupCoverage}</div>
    </section>
    <div style="height:40px"></div>`;
}

/* ---------------- routing ---------------- */

function currentView(hash) {
  if (hash.startsWith('#/patterns') || hash.startsWith('#/p/')) return 'patterns';
  if (hash.startsWith('#/elements') || hash.startsWith('#/e/')) return 'elements';
  if (hash.startsWith('#/dashboard')) return 'dashboard';
  return 'characters';
}

function route() {
  const hash = location.hash || '#/';
  const view = currentView(hash);
  document.querySelectorAll('#tabs a').forEach((a) => a.classList.toggle('on', a.dataset.view === view));
  window.scrollTo(0, 0);

  const detail = hash.match(/^#\/(c|p|e)\/(.+)$/);
  if (detail) {
    const [, kind, id] = detail;
    if (kind === 'c') return renderCharacterDetail(id);
    if (kind === 'p') return renderPatternDetail(id);
    return renderElementDetail(id);
  }
  if (view === 'patterns') return renderPatterns();
  if (view === 'elements') return renderElements();
  if (view === 'dashboard') return renderDashboard();
  return renderCharacters();
}

fetch('data/db.json')
  .then((r) => r.json())
  .then((db) => {
    DB = db;
    db.elements.forEach((e) => (elById[e.id] = e));
    db.patterns.forEach((p) => (patById[p.id] = p));
    db.characters.forEach((c) => (charById[c.id] = c));
    db.groups.forEach((g) => {
      groupById[g.id] = g;
      g.axes.forEach((a) => (axisById[a.id] = a));
    });
    document.getElementById('counts').innerHTML =
      `<b>${db.stats.characters}</b>名 / <b>${db.stats.elements}</b>要素 / <b>${db.stats.patterns}</b>性癖 / <b>${db.stats.axes}</b>軸`;
    window.addEventListener('hashchange', route);
    route();
  })
  .catch((err) => {
    app.innerHTML = `<p class="empty">データを読み込めませんでした（${esc(err.message)}）。<br>ローカルで開く場合は <code>python3 -m http.server</code> 経由で表示してください。</p>`;
  });

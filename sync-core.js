// Синхронизация ворклогов Яндекс Трекера с записями timesheet.
// Общая логика для консоли DevTools (sync.js) и Chrome extension.
// Выполнять в контексте https://tracker.yandex.net: запросы идут к API через адрес
// веб-интерфейса /api/public/v3 с сессией браузера (credentials: 'include'),
// токены и куки не читаются.
//
// entries: [{task, date: 'YYYY-MM-DD', start: ISO с зоной, duration: ISO 8601, comment}]
// apply=false — только чтение (dry-run).
// Результат: [{task, date, action: 'create'|'update'|'same'|'error', from, to, ok, error}]

const TRACKER_API = '/api/public/v3';

// Длительность в минутах; Трекер считает 1 д = 8 ч, 1 н = 5 д
function durationToMinutes(d) {
  const m = String(d).match(/P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?/) || [];
  return (+m[1] || 0) * 2400 + (+m[2] || 0) * 480 + (+m[3] || 0) * 60 + (+m[4] || 0);
}

async function trackerApi(path, opts = {}, base = TRACKER_API) {
  return fetch(base + path, {credentials: 'include', ...opts});
}

async function syncWorklogs(entries, {apply = false, base = TRACKER_API} = {}) {
  const me = await (await trackerApi('/myself', {}, base)).json();
  const json = {'Content-Type': 'application/json'};
  const results = [];
  for (const it of entries) {
    const res = {task: it.task, date: it.date, to: it.duration};
    const r = await trackerApi('/issues/' + it.task + '/worklog?perPage=500', {}, base);
    if (!r.ok) { results.push({...res, action: 'error', error: 'чтение HTTP ' + r.status}); continue; }
    // Только свои ворклоги за этот день: чужие не трогаем
    const mine = (await r.json()).filter(w => w.createdBy && w.createdBy.display === me.display
      && new Date(w.start).toLocaleDateString('sv-SE') === it.date);
    if (mine.find(w => durationToMinutes(w.duration) === durationToMinutes(it.duration))) {
      results.push({...res, action: 'same'}); continue;
    }
    if (mine.length) {
      const w = mine[0];
      if (!apply) { results.push({...res, action: 'update', from: w.duration}); continue; }
      const u = await trackerApi('/issues/' + it.task + '/worklog/' + w.id,
        {method: 'PATCH', headers: json, body: JSON.stringify({duration: it.duration})}, base);
      results.push({...res, action: 'update', from: w.duration, ok: u.ok, error: u.ok ? undefined : 'HTTP ' + u.status});
      continue;
    }
    if (!apply) { results.push({...res, action: 'create'}); continue; }
    const p = await trackerApi('/issues/' + it.task + '/worklog',
      {method: 'POST', headers: json, body: JSON.stringify({start: it.start, duration: it.duration, comment: it.comment})}, base);
    results.push({...res, action: 'create', ok: p.ok, error: p.ok ? undefined : 'HTTP ' + p.status});
  }
  return {user: me.display, apply, results};
}

// Человекочитаемая сводка (без «=» и URL — удобно для консоли и логов)
function formatSyncResult({user, apply, results}) {
  const label = {create: apply ? 'записано' : 'будет', update: apply ? 'обновлено' : 'изменится',
                 same: 'без изменений', error: 'ошибка'};
  const lines = results.map(r => [r.task, r.date, r.ok === false ? 'ошибка' : label[r.action],
    r.action === 'update' ? r.from + ' → ' + r.to : r.to,
    r.error ? '(' + r.error + ')' : ''].join(' ').trim());
  return 'Пользователь ' + user + (apply ? ' (запись)' : ' (dry-run)') + ' | ' + lines.join(' | ');
}

if (typeof module !== 'undefined') module.exports = {syncWorklogs, formatSyncResult, durationToMinutes};

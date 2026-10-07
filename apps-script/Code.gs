// DriveGramOtiner: execution and transfers run on Google's servers.
// Credentials belong in private Script Properties, never in this file.
const DG_LIMIT = 49 * 1000 * 1000; // Leave room for Google's 50 MB multipart POST limit.

function dgConfig_() {
  const p = PropertiesService.getScriptProperties();
  const config = {token: p.getProperty('BOT_TOKEN'), chat: p.getProperty('PRIVATE_CHAT_ID'),
    folder: p.getProperty('DRIVE_FOLDER_ID'), props: p};
  if (!/^\d+:[\w-]+$/.test(config.token || '') || !/^\d+$/.test(config.chat || '') ||
      !/^[\w-]+$/.test(config.folder || '')) throw new Error('Missing private Script Properties.');
  return config;
}

function dgTelegram_(c, method, payload, sending) {
  let response;
  try {
    response = UrlFetchApp.fetch('https://api.telegram.org/bot' + c.token + '/' + method,
      {method: 'post', payload: payload, muteHttpExceptions: true, followRedirects: false});
  } catch (_) {
    // Never expose Google's exception text: it can contain the bot token URL.
    throw new Error(sending ? 'SEND_UNKNOWN' : 'TELEGRAM_NETWORK');
  }
  let data;
  try { data = JSON.parse(response.getContentText()); } catch (_) { throw new Error('SEND_UNKNOWN'); }
  if (!data || typeof data.ok !== 'boolean') throw new Error('SEND_UNKNOWN');
  if (!data.ok) {
    const error = new Error(Number(data.error_code) >= 500 ? 'SEND_UNKNOWN' : 'TELEGRAM_REJECTED');
    error.retryAfter = data.parameters && Number(data.parameters.retry_after);
    throw error;
  }
  return data.result;
}

function dgDrive_(path, query, binary) {
  let response;
  try {
    response = UrlFetchApp.fetch('https://www.googleapis.com/drive/v3/' + path + (query ? '?' + query : ''),
      {headers: {Authorization: 'Bearer ' + ScriptApp.getOAuthToken()}, muteHttpExceptions: true,
       followRedirects: false});
  } catch (_) { throw new Error('DRIVE_NETWORK'); }
  if (response.getResponseCode() !== 200) throw new Error('DRIVE_ACCESS');
  return binary ? response.getBlob() : JSON.parse(response.getContentText());
}

function dgFiles_(c) {
  let files = [], page = '';
  for (let i = 0; i < 10; i++) {
    const query = 'q=' + encodeURIComponent("'" + c.folder + "' in parents and trashed = false") +
      '&pageSize=50&fields=' + encodeURIComponent('nextPageToken,files(id,name,size,mimeType,md5Checksum,version,parents)') +
      '&orderBy=createdTime desc' + (page ? '&pageToken=' + encodeURIComponent(page) : '');
    const result = dgDrive_('files', query, false);
    files = files.concat(result.files || []);
    page = result.nextPageToken;
    if (!page) break;
  }
  if (page) throw new Error('FOLDER_TOO_LARGE');
  return files.filter(f => /^video\//.test(f.mimeType) || /\.(mp4|mkv|mov|avi|webm|m4v|mpeg|mpg|ts)$/i.test(f.name))
    .map(f => {
      f.key = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
        c.folder + ':' + f.id + ':' + (f.md5Checksum || f.version) + ':' + f.size)
        .map(b => ('0' + ((b + 256) % 256).toString(16)).slice(-2)).join('').slice(0, 24);
      return f;
    });
}

function dgState_(c, f) {
  const raw = c.props.getProperty('f:' + f.key);
  return raw ? JSON.parse(raw) : {status: Number(f.size) > DG_LIMIT ? 'too_large' : 'ready'};
}

function dgSave_(c, f, state) { c.props.setProperty('f:' + f.key, JSON.stringify(state)); }

function dgSay_(c, text, keyboard) {
  const payload = {chat_id: c.chat, text: text};
  if (keyboard) payload.reply_markup = JSON.stringify({inline_keyboard: keyboard});
  return dgTelegram_(c, 'sendMessage', payload, false);
}

function dgCatalog_(c, files, page) {
  const statuses = {ready: 'آماده', queued: 'در صف', sent: 'ارسال‌شده', sending: 'نیاز به بررسی',
    unknown: 'نیاز به بررسی', failed: 'خطای قطعی', too_large: 'بزرگ‌تر از سقف این نسخه'};
  const start = page * 8, selected = files.slice(start, start + 8);
  const lines = ['ویدیوهای Drive — اجرا روی سرور گوگل', 'فایل اصلی بدون تبدیل ارسال می‌شود؛ سقف امن این نسخه ۴۹ مگابایت است.'];
  const rows = [];
  selected.forEach((f, i) => {
    const state = dgState_(c, f);
    lines.push((i + 1) + '. ' + f.name.replace(/[\r\n]/g, ' ').slice(0, 140) + ' — ' +
      (Number(f.size) / 1000000).toFixed(1) + ' MB — ' + (statuses[state.status] || state.status));
    if (['ready', 'failed'].includes(state.status) && Number(f.size) <= DG_LIMIT)
      rows.push([{text: 'ارسال فایل ' + (i + 1), callback_data: 'dg:send:' + f.key}]);
    if (['unknown', 'sending'].includes(state.status))
      rows.push([{text: 'بررسی فایل ' + (i + 1), callback_data: 'dg:review:' + f.key}]);
  });
  if (!selected.length) lines.push('ویدیویی در پوشه پیدا نشد.');
  const nav = [];
  if (page) nav.push({text: 'قبلی', callback_data: 'dg:list:' + (page - 1)});
  if (start + 8 < files.length) nav.push({text: 'بعدی', callback_data: 'dg:list:' + (page + 1)});
  if (nav.length) rows.push(nav);
  rows.push([{text: 'تازه‌سازی', callback_data: 'dg:list:' + page}]);
  dgSay_(c, lines.join('\n\n'), rows);
}

function dgUpdates_(c, files) {
  const offset = Number(c.props.getProperty('UPDATE_OFFSET') || 0);
  const updates = dgTelegram_(c, 'getUpdates', {offset: String(offset), timeout: '0', limit: '20',
    allowed_updates: JSON.stringify(['message', 'callback_query'])}, false);
  updates.forEach(u => {
    if (!Number.isInteger(u.update_id) || u.update_id < offset) return;
    // A reply interruption must never replay a file-send instruction.
    c.props.setProperty('UPDATE_OFFSET', String(u.update_id + 1));
    const cb = u.callback_query, msg = cb ? cb.message : u.message;
    const sender = cb ? cb.from : (msg && msg.from);
    if (!msg || !sender || sender.is_bot || msg.chat.type !== 'private' ||
        String(msg.chat.id) !== c.chat || sender.id !== msg.chat.id) return;
    if (!cb) {
      const command = (msg.text || '').split(/\s|@/)[0];
      if (['/videos', '/status', '/start', '/help'].includes(command)) dgCatalog_(c, files, 0);
      return;
    }
    const data = cb.data || '';
    if (!data.startsWith('dg:')) return;
    dgTelegram_(c, 'answerCallbackQuery', {callback_query_id: cb.id}, false);
    if (/^dg:list:\d{1,5}$/.test(data)) { dgCatalog_(c, files, Number(data.split(':')[2])); return; }
    const f = files.find(item => item.key === data.split(':')[2]);
    if (!f) { dgSay_(c, 'فایل تغییر کرده یا حذف شده؛ فهرست را تازه‌سازی کنید.'); return; }
    const state = dgState_(c, f);
    if (data.startsWith('dg:review:') && ['unknown', 'sending'].includes(state.status)) {
      dgSay_(c, 'اول پی‌وی را بررسی کنید. فقط اگر این فایل واقعاً نرسیده، عدم دریافت را تأیید کنید.',
        [[{text: 'بررسی کردم؛ فایل نرسیده — تلاش مجدد', callback_data: 'dg:retry:' + f.key}]]);
    } else if ((data.startsWith('dg:send:') && ['ready', 'failed'].includes(state.status)) ||
               (data.startsWith('dg:retry:') && ['unknown', 'sending'].includes(state.status))) {
      if (Number(f.size) > DG_LIMIT) { dgSay_(c, 'فایل بیش از سقف این نسخه است؛ تقسیم یا تبدیل نمی‌شود.'); return; }
      dgSave_(c, f, {status: 'queued'});
      dgSay_(c, 'فایل کامل برای ارسال به همین پی‌وی در صف قرار گرفت.');
    }
  });
}

function dgTransfer_(c, f) {
  // Obtain and validate the entire original before beginning a Telegram send.
  const fields = 'fields=id,name,size,md5Checksum,version,parents,mimeType';
  const before = dgDrive_('files/' + encodeURIComponent(f.id), fields, false);
  const valid = meta => (meta.parents || []).includes(c.folder) && String(meta.size) === String(f.size) &&
    (f.md5Checksum ? meta.md5Checksum === f.md5Checksum : meta.version === f.version);
  if (!valid(before) || Number(before.size) > DG_LIMIT) throw new Error('SOURCE_CHANGED');
  const blob = dgDrive_('files/' + encodeURIComponent(f.id), 'alt=media', true).setName(f.name);
  const bytes = blob.getBytes();
  if (bytes.length !== Number(f.size)) throw new Error('INCOMPLETE_DOWNLOAD');
  if (f.md5Checksum) {
    const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, bytes)
      .map(b => ('0' + ((b + 256) % 256).toString(16)).slice(-2)).join('');
    if (digest !== f.md5Checksum) throw new Error('CHECKSUM_MISMATCH');
  }
  if (!valid(dgDrive_('files/' + encodeURIComponent(f.id), fields, false))) throw new Error('SOURCE_CHANGED');
  dgSave_(c, f, {status: 'sending', at: Date.now()});
  try {
    const result = dgTelegram_(c, 'sendDocument', {chat_id: c.chat, document: blob,
      caption: f.name.slice(0, 1024), disable_content_type_detection: 'true'}, true);
    if (!result || String(result.chat.id) !== c.chat || !result.message_id || !result.document.file_id)
      throw new Error('SEND_UNKNOWN');
    dgSave_(c, f, {status: 'sent', message: result.message_id, file: result.document.file_id, at: Date.now()});
    console.log('Original file delivery confirmed.');
  } catch (error) {
    dgSave_(c, f, {status: error.message === 'TELEGRAM_REJECTED' ? 'failed' : 'unknown', at: Date.now()});
    if (error.retryAfter) c.props.setProperty('RETRY_AFTER', String(Date.now() + error.retryAfter * 1000));
    throw new Error('Transfer stopped; check /videos.');
  }
}

function drivegramTick() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    const c = dgConfig_();
    if (Date.now() < Number(c.props.getProperty('RETRY_AFTER') || 0)) return;
    const chat = dgTelegram_(c, 'getChat', {chat_id: c.chat}, false);
    const bot = dgTelegram_(c, 'getMe', {}, false);
    if (chat.type !== 'private' || String(chat.id) !== c.chat || bot.username !== 'DriveGramOtiner_bot')
      throw new Error('Private destination or bot mismatch.');
    const files = dgFiles_(c);
    dgUpdates_(c, files);
    const next = files.find(f => ['ready', 'queued'].includes(dgState_(c, f).status) && Number(f.size) <= DG_LIMIT);
    if (next) dgTransfer_(c, next);
    c.props.setProperty('LAST_OK', new Date().toISOString());
  } catch (_) {
    // Fail closed, keep unknown sends for review, and do not leak credentials in execution logs.
    console.error('DriveGram stopped safely. Check private configuration, authorization and /videos.');
  } finally { lock.releaseLock(); }
}

function installDriveGram() {
  const c = dgConfig_();
  const me = dgTelegram_(c, 'getMe', {}, false);
  const chat = dgTelegram_(c, 'getChat', {chat_id: c.chat}, false);
  const hook = dgTelegram_(c, 'getWebhookInfo', {}, false);
  if (me.username !== 'DriveGramOtiner_bot' || chat.type !== 'private' || String(chat.id) !== c.chat)
    throw new Error('Private destination or bot mismatch.');
  if (hook.url) throw new Error('An existing webhook must be reviewed before switching receivers.');
  dgFiles_(c); // Verify read-only access before installing anything.
  if (!ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction() === 'drivegramTick'))
    ScriptApp.newTrigger('drivegramTick').timeBased().everyMinutes(1).create();
  dgTelegram_(c, 'setMyCommands', {scope: JSON.stringify({type: 'chat', chat_id: c.chat}),
    commands: JSON.stringify([{command: 'videos', description: 'Drive videos'},
      {command: 'status', description: 'Transfer status'}])}, false);
  dgCatalog_(c, dgFiles_(c), 0);
  console.log('Cloud trigger installed; private catalog sent.');
}

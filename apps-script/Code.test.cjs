const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');

function runtime() {
  const values = {BOT_TOKEN: '1:fake', PRIVATE_CHAT_ID: '123', DRIVE_FOLDER_ID: 'folder'};
  const requests = [];
  let disconnect = false;
  const bytes = Buffer.from('complete-original-video');
  const file = {id: 'video', name: 'original.mp4', size: String(bytes.length), mimeType: 'video/mp4',
    version: '1', md5Checksum: crypto.createHash('md5').update(bytes).digest('hex'), parents: ['folder']};
  const blob = {setName(name) { this.name = name; return this; }, getBytes() { return [...bytes]; }};
  const response = data => ({getContentText: () => JSON.stringify(data), getResponseCode: () => 200,
    getBlob: () => blob});
  const context = vm.createContext({console: {log() {}, error() {}},
    PropertiesService: {getScriptProperties: () => ({getProperty: k => values[k] || null,
      setProperty: (k, v) => { values[k] = v; }})},
    Utilities: {DigestAlgorithm: {SHA_256: 'sha256', MD5: 'md5'}, computeDigest: (algorithm, data) =>
      [...crypto.createHash(algorithm).update(typeof data === 'string' ? data : Buffer.from(data)).digest()]},
    ScriptApp: {getOAuthToken: () => 'mock-access'},
    UrlFetchApp: {fetch(url, options) {
      requests.push({url, options});
      if (url.includes('googleapis.com'))
        return response(url.includes('/files?') ? {files: [file]} : file);
      if (url.endsWith('/sendDocument')) {
        if (disconnect) throw new Error('secret-bearing transport URL');
        return response({ok: true, result: {chat: {id: 123}, message_id: 12, document: {file_id: 'tg-file'}}});
      }
      return response({ok: true, result: url.endsWith('/getUpdates') ? [] : {}});
    }}});
  vm.runInContext(fs.readFileSync(__dirname + '/Code.gs', 'utf8'), context);
  const c = context.dgConfig_(), f = context.dgFiles_(c)[0];
  return {context, values, requests, bytes, blob, c, f, disconnect: () => { disconnect = true; }};
}

test('cloud transfer preserves the entire original and confirms private message', () => {
  const r = runtime();
  r.context.dgTransfer_(r.c, r.f);
  const send = r.requests.find(x => x.url.endsWith('/sendDocument'));
  assert.equal(send.options.payload.chat_id, '123');
  assert.equal(send.options.payload.document, r.blob);
  assert.equal(r.blob.name, 'original.mp4');
  assert.deepEqual(Buffer.from(r.blob.getBytes()), r.bytes);
  assert.equal(r.context.dgState_(r.c, r.f).status, 'sent');
});

test('an interrupted upload is retained for review and is not selected automatically', () => {
  const r = runtime();
  r.disconnect();
  assert.throws(() => r.context.dgTransfer_(r.c, r.f), /Transfer stopped/);
  assert.equal(r.context.dgState_(r.c, r.f).status, 'unknown');
  assert.equal(['ready', 'queued'].includes(r.context.dgState_(r.c, r.f).status), false);
});

test('oversize original is rejected before upload', () => {
  const r = runtime();
  r.f.size = '50000000';
  assert.equal(r.context.dgState_(r.c, r.f).status, 'too_large');
  assert.throws(() => r.context.dgTransfer_(r.c, r.f), /SOURCE_CHANGED/);
  assert.equal(r.requests.some(x => x.url.endsWith('/sendDocument')), false);
});

test('a foreign private account cannot enumerate Drive or queue a callback', () => {
  const r = runtime();
  r.context.dgTelegram_ = (c, method) => {
    assert.equal(method, 'getUpdates');
    return [{update_id: 4, callback_query: {id: 'cb', from: {id: 999},
      message: {chat: {type: 'private', id: 999}}, data: 'dg:send:' + r.f.key}}];
  };
  r.context.dgUpdates_(r.c, [r.f]);
  assert.equal(r.context.dgState_(r.c, r.f).status, 'ready');
  assert.equal(r.values.UPDATE_OFFSET, '5');
});

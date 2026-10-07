"use strict";
const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const selected = new Set();
let page = 1, pages = 1, state = null, busy = false;
const number = n => new Intl.NumberFormat("fa-IR").format(n);
const size = n => n >= 1024 ** 3 ? `${number((n / 1024 ** 3).toFixed(1))} گیگابایت` : `${number((n / 1024 ** 2).toFixed(1))} مگابایت`;
const date = d => d ? new Date(d).toLocaleString("fa-IR") : "—";
function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function showError(text) { $("alert").textContent = text; $("alert").hidden = false; }
async function post(url, body) {
  try {
    const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: JSON.stringify(body)});
    if (response.status === 401) { location.href = "/login"; return false; }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || data.detail || "درخواست کامل نشد.");
    $("alert").hidden = true; return true;
  } catch (error) { showError(error.message); return false; }
}
async function action(id, action, confirmation) { if (await post("/api/jobs/action", {ids: [id], action, confirmation})) { selected.delete(id); await refresh(); } }
function button(text, callback) { const b = el("button", "ghost", text); b.type = "button"; b.addEventListener("click", callback); return b; }
function renderJob(job) {
  const row = el("article", "job");
  const checkbox = el("input"); checkbox.type = "checkbox"; checkbox.disabled = !job.can_queue; checkbox.checked = selected.has(job.id) && job.can_queue;
  checkbox.setAttribute("aria-label", `انتخاب ${job.name}`);
  checkbox.addEventListener("change", () => { checkbox.checked ? selected.add(job.id) : selected.delete(job.id); updateSelection(); });
  const description = el("div"); description.append(el("div", "job-name", job.name));
  const meta = el("div", "job-meta"); meta.append(el("span", "", size(job.size)), el("span", "", `تلاش ${number(job.attempts)}`), el("span", "", job.completed_at ? `انتقال: ${date(job.completed_at)}` : `کشف: ${date(job.created_at)}`)); description.append(meta);
  if (job.error) description.append(el("div", "job-error", job.error));
  const status = el("div", "job-status"); status.append(el("span", `badge ${job.status}`, job.label));
  if (job.status === "downloading") { const progress = el("progress"); progress.max = job.size || 1; progress.value = job.downloaded; status.append(progress, el("div", "stage", job.size ? `${number(Math.min(100, Math.floor(job.downloaded / job.size * 100)))}٪ دریافت شده` : "در حال دریافت")); }
  if (job.status === "uploading") status.append(el("div", "stage", "منتظر پاسخ تلگرام…"));
  const actions = el("div", "job-actions");
  if (job.can_queue) actions.append(button(job.status === "discovered" ? "انتقال" : "تلاش مجدد", () => action(job.id, "queue")));
  if (job.can_cancel && !job.review) actions.append(button("لغو", () => action(job.id, "cancel")));
  if (job.link) { const link = el("a", "", "مشاهده پیام ↗"); link.href = job.link; link.target = "_blank"; link.rel = "noopener noreferrer"; actions.append(link); }
  if (job.review) {
    const review = el("div", "review"); const label = el("label"); const check = el("input"); check.type = "checkbox";
    label.append(check, el("span", "", "کانال را بررسی کردم و مطمئنم این نسخه ارسال نشده؛ Bot API دیگر در حال پردازش آن نیست."));
    const retry = button("ارسال پس از بررسی", () => action(job.id, "review_retry", "checked_no_message")); retry.disabled = true;
    check.addEventListener("change", () => { retry.disabled = !check.checked; });
    review.append(label, retry, button("بستن بررسی بدون ارسال", () => action(job.id, "review_close"))); description.append(review);
  }
  row.append(checkbox, description, status, actions); return row;
}
function updateSelection() { $("queue-selected").disabled = selected.size === 0; $("queue-selected").textContent = selected.size ? `انتقال ${number(selected.size)} فایل انتخاب‌شده` : "انتقال انتخاب‌شده‌ها"; }
async function refresh() {
  if (busy) return; busy = true;
  try {
    const response = await fetch(`/api/status?page=${page}`);
    if (response.status === 401) { location.href = "/login"; return; }
    if (!response.ok) throw new Error("خواندن وضعیت سرویس ممکن نیست.");
    state = await response.json(); pages = state.pages;
    $("google").textContent = state.google; $("telegram").textContent = state.telegram; $("oauth").disabled = !state.google_can_connect;
    $("last-scan").textContent = `آخرین اسکن: ${date(state.last_scan)}`;
    $("disk").textContent = state.disk_free == null ? "در انتظار اتصال پردازشگر" : size(state.disk_free);
    $("disk-meter").value = state.disk_total ? (state.disk_total - state.disk_free) / state.disk_total * 100 : 0;
    $("queue").textContent = `${number(state.queue_count)} در صف`; $("sync").checked = state.auto_sync;
    $("worker").textContent = state.worker_ok ? "worker فعال" : "worker در دسترس نیست"; $("worker").className = `badge ${state.worker_ok ? "good" : "failed"}`;
    for (const id of [...selected]) { if (!state.jobs.some(j => j.id === id && j.can_queue)) selected.delete(id); }
    // Preserve the review checkbox while polling: replacing focused controls discards deliberate input.
    if (!$("jobs").contains(document.activeElement)) {
      $("jobs").replaceChildren(...(state.jobs.length ? state.jobs.map(renderJob) : [el("div", "empty", "هنوز ویدیویی ثبت نشده است. اتصال Drive و اجرای worker را بررسی کنید.")]));
    }
    $("page-info").textContent = `صفحه ${number(page)} از ${number(pages)}`; $("prev").disabled = page <= 1; $("next").disabled = page >= pages; updateSelection();
  } catch (error) { showError(error.message); } finally { busy = false; }
}
$("sync").addEventListener("change", async () => { const enabled = $("sync").checked; if (!await post("/api/sync", {enabled})) $("sync").checked = !enabled; await refresh(); });
$("queue-selected").addEventListener("click", async () => { if (await post("/api/jobs/action", {ids: [...selected], action: "queue"})) { selected.clear(); await refresh(); } });
$("select-all").addEventListener("change", () => { selected.clear(); if ($("select-all").checked && state) for (const j of state.jobs) if (j.can_queue) selected.add(j.id); $("jobs").replaceChildren(...state.jobs.map(renderJob)); updateSelection(); });
$("prev").addEventListener("click", () => { if (page > 1) { page--; selected.clear(); refresh(); } });
$("next").addEventListener("click", () => { if (page < pages) { page++; selected.clear(); refresh(); } });
refresh(); setInterval(refresh, 3000);

"""Private, paired-owner commands; all deliveries use the durable transfer queue."""
from sqlalchemy import select

from drivegram.errors import ServiceError
from drivegram.models import Job
from drivegram.queue import current_scope, queue_selected

PAGE_SIZE = 8
STATUS = {"discovered": "آماده", "queued": "در صف", "downloading": "در حال دانلود",
          "uploading": "در حال ارسال", "completed": "ارسال‌شده", "failed": "ناموفق", "canceled": "لغوشده"}


def catalog(session, settings, chat_id, page=0):
    scope = current_scope(session, settings)
    jobs = session.scalars(select(Job).where(Job.source_scope == scope)
                           .order_by(Job.created_at.desc(), Job.id).offset(page * PAGE_SIZE).limit(PAGE_SIZE + 1)).all()
    text = ["ویدیوهای پوشهٔ Drive", "برای دریافت فایل کامل، دکمهٔ ارسال را بزنید."]
    buttons = []
    for number, job in enumerate(jobs[:PAGE_SIZE], 1):
        name = "".join(c for c in job.original_name if c.isprintable())[:140]
        state = "نیاز به بررسی در پنل" if job.needs_review else STATUS.get(job.status, job.status)
        text.append(f"{number}. {name} — {job.size_bytes / 1_000_000:.1f} MB — {state}")
        if (job.status in {"discovered", "failed", "canceled"} and not job.needs_review
                and job.size_bytes <= settings.max_file_size_bytes):
            buttons.append([{"text": f"ارسال فایل {number}", "callback_data": f"dg:send:{job.id}"}])
    if not jobs:
        text.append("هنوز ویدیویی پیدا نشده؛ پس از آپلود، اسکن دوره‌ای پوشه را بررسی می‌کند.")
    navigation = []
    if page:
        navigation.append({"text": "قبلی", "callback_data": f"dg:list:{page - 1}"})
    if len(jobs) > PAGE_SIZE:
        navigation.append({"text": "بعدی", "callback_data": f"dg:list:{page + 1}"})
    if navigation:
        buttons.append(navigation)
    buttons.append([{"text": "تازه‌سازی", "callback_data": f"dg:list:{page}"}])
    return ("sendMessage", {"chat_id": chat_id, "text": "\n\n".join(text),
                            "reply_markup": {"inline_keyboard": buttons}})


def owner_actions(session, settings, control, update):
    callback = update.get("callback_query")
    message = callback.get("message", {}) if callback else update.get("message", {})
    sender = (callback or message).get("from", {})
    chat = message.get("chat", {})
    # Never reveal the private Drive catalog or accept send requests from another account.
    if (not control.private_chat_id or chat.get("type") != "private" or sender.get("is_bot")
            or str(chat.get("id")) != control.private_chat_id or sender.get("id") != chat.get("id")):
        return []
    actions = []
    chat_id = control.private_chat_id
    if callback:
        data = callback.get("data", "")
        if not data.startswith("dg:"):
            return []
        answer = {"callback_query_id": callback.get("id"), "text": ""}
        if data.startswith("dg:list:"):
            try:
                page = int(data.removeprefix("dg:list:"))
                if not 0 <= page <= 100_000:
                    raise ValueError()
                actions.append(catalog(session, settings, chat_id, page))
            except ValueError:
                answer["text"] = "درخواست معتبر نیست."
        elif data.startswith("dg:send:"):
            job = session.get(Job, data.removeprefix("dg:send:"))
            try:
                if job is None:
                    raise ServiceError("missing", "فایل پیدا نشد؛ فهرست را تازه‌سازی کنید.")
                queue_selected(session, job, settings)
                answer["text"] = "فایل برای ارسال کامل به همین پی‌وی در صف قرار گرفت."
            except ServiceError as error:
                answer["text"] = error.message[:190]
            actions.append(("sendMessage", {"chat_id": chat_id, "text": answer["text"]}))
        actions.insert(0, ("answerCallbackQuery", answer))
    else:
        command = message.get("text", "").split(maxsplit=1)
        command = command[0].split("@")[0] if command else ""
        if command in {"/videos", "/status"}:
            actions.append(catalog(session, settings, chat_id))
        elif command in {"/start", "/help"}:
            actions.append(("sendMessage", {"chat_id": chat_id,
                "text": "Drive متصل است. با /videos ویدیوها و وضعیت ارسالشان را ببینید و فایل کامل را دریافت کنید."
                        "\nارسال فقط به همین پی‌وی انجام می‌شود. فایل‌های نامشخص باید ابتدا در پنل بررسی شوند."}))
    return actions

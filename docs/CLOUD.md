# اجرای ابری بدون کامپیوتر شخصی

مسیر دادهٔ مورد نظر: **آپلود شما به Drive → دانلود روی میزبان ابری → آپلود از همان میزبان به تلگرام → پی‌وی خودتان**. اتصال و اینترنت کامپیوتر شخصی فقط برای آپلود اولیه و تنظیم حساب لازم است؛ worker روی کامپیوتر، حتی اگر پنل روی Vercel باشد، این هدف را برآورده نمی‌کند. خود تلگرام حساب ربات را ارائه می‌کند و کد برنامه باید روی میزبانی جدا اجرا شود.

## اجرای مستقل تا ۵۰ مگابایت

برای حالت موقت فایل کامل تا ۵۰ مگابایت، `compose.server.yaml` دیتابیس، پنل و worker را روی یک میزبان Linux اجرا می‌کند؛ Local Bot API و `api_id/api_hash` لازم نیست. اتصال تلگرام مستقیم است و تنظیم پروکسی کامپیوتر شخصی به این اجرا منتقل نمی‌شود. فایل اصلی تقسیم یا تبدیل نمی‌شود.

پس از انتخاب میزبان و تنظیم `.env` خصوصی آن، `DATABASE_URL` باید دیتابیس همین Compose با hostname `db` را نشان دهد. پنل پیش‌فرض فقط روی loopback میزبان باز است؛ برای تنظیم اولیه از SSH tunnel با `http://localhost:8000` و redirect متناظر Google استفاده کنید، یا دامنه و HTTPS را پیش از عمومی‌کردن پنل تنظیم کنید. برای حفظ اتصال موجود، انتقال امن رکورد OAuth رمزگذاری‌شده و مقصد خصوصی، با همان کلید Fernet، لازم است؛ صرف کپی `.env` مجوز Drive ذخیره‌شده در دیتابیس را منتقل نمی‌کند. در مهاجرت، worker کامپیوتر را متوقف کنید تا دو پردازشگر مستقل یک پوشه را هم‌زمان ارسال نکنند.

```sh
docker compose -f compose.server.yaml up -d --build
```

این فایل استقرار آماده شده است، اما تا اتصال میزبان واقعی و تأیید یک ارسال واقعی از آن، انتقال ابری فعال محسوب نمی‌شود. نسخهٔ فعلی Vercel فقط پنل است و این Compose را اجرا نمی‌کند.

## پنل Vercel و فایل‌های بزرگ

پنل روی Vercel اجرا می‌شود. انتقال‌های دائمی و Local Bot API روی یک میزبان Linux با Docker و دیسک پایدار اجرا می‌شوند. PostgreSQL مدیریت‌شده با TLS بین این دو مشترک است. کامپیوتر شخصی در زمان اجرا نقشی ندارد.

Vercel stateless است؛ حتی پشتیبانی OCI آن دیسک پایدار و mount مشترک این معماری را فراهم نمی‌کند. Cron رایگان آن نیز اسکن دقیقه‌ای ندارد. worker را داخل Function یا درخواست وب راه‌اندازی نکنید.

## پنل

ورودی ASGI در `drivegram/vercel.py` است. `.vercelignore` تمام `.env`ها و فایل‌های محلی را حذف می‌کند. در نبود تنظیمات ضروری، صفحهٔ وضعیت با اعلام غیرفعال بودن انتقال‌ها و health HTTP 503 نمایش داده می‌شود؛ اتصال ساختگی تولید نمی‌شود.

متغیرهای Production پروژه:

- `DATABASE_URL`: دیتابیس جدید و اختصاصی DriveGram؛ `postgresql+psycopg://…?sslmode=require`؛ ترجیحاً endpoint pooler ارائه‌دهنده.
- `ADMIN_USERNAME` و `ADMIN_PASSWORD_HASH`: هش Argon2 رمز مدیر؛ رمز خام لازم نیست.
- `SESSION_SECRET`: رشتهٔ تصادفی حداقل ۳۲ کاراکتر.
- `TOKEN_ENCRYPTION_KEY`: کلید Fernet مشترک با worker. تغییر آن مجوز ذخیره‌شدهٔ Google را غیرقابل خواندن می‌کند.
- `GOOGLE_CLIENT_ID`، `GOOGLE_CLIENT_SECRET`، `GOOGLE_DRIVE_FOLDER_ID`.
- `PUBLIC_BASE_URL=https://drivegramotiner.vercel.app` و `GOOGLE_REDIRECT_URI=https://drivegramotiner.vercel.app/oauth/callback` یا دامنهٔ واقعی پروژه؛ همان redirect را در Google Console ثبت کنید.

ورودی Vercel به‌صورت اجباری secure cookies، حالت remote worker و اتصال بدون pool داخلی SQLAlchemy دارد. **توکن ربات، Telegram API hash/id و فایل `.env` را به Vercel نفرستید.** پنل برای کنترل صف به توکن ربات نیاز ندارد.

## پردازشگر

روی میزبان Linux همین مخزن را clone کنید و `.env` مخصوص آن میزبان را از `.env.example` بسازید. مراحل README دربارهٔ Google OAuth، ربات موجود، logOut و اتصال پی‌وی از پنل همچنان لازم است. `DATABASE_URL` و کلید Fernet باید با پنل یکسان باشند. اطلاعات Telegram فقط در `.env` همین میزبان قرار بگیرند. `TEMP_DIR=/transfers` و `TELEGRAM_BOT_API_URL=http://bot-api:8081`.

```sh
docker compose -f compose.cloud.yaml up -d --build
```

این Compose ابتدا migration را اجرا می‌کند؛ worker و Bot API با restart policy و دیسک مشترک پایدار اجرا می‌شوند. هیچ پورت عمومی برای این دو باز نمی‌شود. migration `0002` برای گزارش دیسک در پنل لازم است. قبل از ارتقا backup بگیرید. پس از راه‌اندازی، health و انتقال یک فایل واقعی را تأیید کنید؛ انتشار پنل اثبات انتقال موفق نیست.

میزبان، دیتابیس، backup و مانیتورینگ باید پیش از اعلام آمادگی تکمیل شوند. بودجه و دسترسی میزبان به اطلاعات صاحب حساب نیاز دارند. restart policy شروع مجدد پس از reboot را پوشش می‌دهد، ولی خرابی میزبان یا ارتقای زیرساخت را به‌تنهایی حل نمی‌کند.

مراجع: https://vercel.com/docs/frameworks/backend/fastapi، https://vercel.com/docs/functions/container-images، https://vercel.com/docs/cron-jobs/usage-and-pricing.

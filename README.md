# DriveGramOtiner

سرویس تک‌مدیره برای انتقال مستقیم ویدیوهای **پوشه خصوصی Google Drive** به **کانال خصوصی Telegram**، بدون دانلود روی دستگاه مدیر، بدون عمومی‌کردن فایل و بدون تبدیل یا کاهش کیفیت. ربات مورد استفاده فقط `@DriveGramOtiner_bot` است.

FastAPI پنل فارسی را اجرا می‌کند؛ worker مستقل دانلود و ارسال را انجام می‌دهد؛ صف، وضعیت‌ها و refresh token رمزگذاری‌شده در PostgreSQL نگهداری می‌شوند. Local Bot API از **سورس رسمی Telegram** با commit مشخص ساخته می‌شود. فایل‌های موقت در مسیر مشترک `/transfers` قرار دارند. سورس Drive هیچ‌وقت حذف یا تغییر داده نمی‌شود.

## شروع سریع

نیازمندی: Python 3.12 برای ایجاد تنظیمات؛ Docker Engine/Desktop و Docker Compose v2 با Linux containers. استقرار اصلی روی سرور Linux خارج از ایران با ارتباط مستقیم به Google و Telegram است. Laragon/PHP برای این پروژه لازم نیست.

```powershell
git clone https://github.com/adib-rahamani-dev/DriveGramOtiner.git
cd DriveGramOtiner
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe scripts/setup_env.py
```

در Linux:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/python scripts/setup_env.py
chmod 600 .env
```

`setup_env.py` کلید Fernet، secret سشن، رمز دیتابیس و رمز مدیر تصادفی می‌سازد و **هیچ‌کدام را چاپ نمی‌کند**. اگر `.env` از قبل موجود باشد آن را تغییر نمی‌دهد. فایل `.env` ساخته‌شده را فقط در ویرایشگر محلی باز کنید؛ `ADMIN_PASSWORD` رمز ورود است. برای توسعه HTTP مقدار `COOKIE_SECURE=false` است؛ روی سرور حتماً `true` کنید. توکن ربات موجود را فقط در `.env` وارد کنید. `.env.example` هیچ توکن واقعی ندارد. از `docker compose config` بدون `--quiet` استفاده نکنید، چون مقادیر محیط را چاپ می‌کند.

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

پنل توسعه: [http://localhost:8000](http://localhost:8000)، نام کاربری پیش‌فرض `admin`. اولین build سرور رسمی Bot API شامل کامپایل TDLib است؛ زمان و حافظه بیشتری می‌خواهد (حداقل ۴ گیگابایت RAM و فضای کافی توصیه می‌شود). در نبود `api_id/api_hash` سرویس Bot API منتظر تنظیمات می‌ماند و health آن سالم نمی‌شود؛ پنل و worker برای راه‌اندازی همچنان اجرا می‌شوند. در نبود OAuth یا کانال نیز وضعیت «نیاز به تنظیم اتصال» نمایش داده می‌شود و هیچ انتقالی شروع نمی‌شود.

بعد از تغییر `.env`:

```bash
docker compose up -d --force-recreate app worker bot-api
```

پس از تغییر سورس/نسخه، `docker compose up -d --build` را اجرا کنید؛ سرویس migration قبل از app و worker تمام می‌شود. از اجرای چند migration هم‌زمان خودداری کنید. تغییر `POSTGRES_PASSWORD` به‌تنهایی رمز دیتابیس موجود در volume را عوض نمی‌کند؛ رمز role را نیز با ابزار مدیریت PostgreSQL تغییر دهید.

## راه‌اندازی Google OAuth

1. در [Google Cloud Console](https://console.cloud.google.com/) پروژه بسازید و Google Drive API را فعال کنید.
2. OAuth consent screen را تنظیم کنید. برای استفاده شخصی در حالت Testing، ایمیل خودتان را Test user قرار دهید. طبق [مستندات Google](https://developers.google.com/identity/protocols/oauth2#expiration)، refresh token برنامه External در حالت Testing با scope درایو معمولاً پس از ۷ روز منقضی می‌شود؛ برای استفاده طولانی، وضعیت انتشار/الزامات مربوط را بررسی کنید.
3. OAuth client از نوع **Web application** بسازید. Redirect URI را دقیقاً برابر `GOOGLE_REDIRECT_URI` تنظیم کنید؛ توسعه `http://localhost:8000/oauth/callback`، سرور `https://YOUR_DOMAIN/oauth/callback`.
4. `GOOGLE_CLIENT_ID`، `GOOGLE_CLIENT_SECRET` و `GOOGLE_DRIVE_FOLDER_ID` را وارد کنید. شناسه پوشه بخش بعد از `/folders/` در آدرس Drive است، نه URL کامل.
5. سرویس‌ها را recreate کنید؛ از پنل «اتصال / تمدید مجوز گوگل» را بزنید و با حساب صاحب پوشه مجوز بدهید. جریان OAuth از state، انقضا و PKCE استفاده می‌کند. refresh token با Fernet در دیتابیس رمزگذاری می‌شود؛ access token فقط در RAM worker است. کلید `TOKEN_ENCRYPTION_KEY` خارج از دیتابیس در `.env` باقی می‌ماند.

**انتخاب scope:** کمترین scope فقط‌خواندنی که فایل‌های از پیش موجود در یک پوشه دلخواه را فهرست و دانلود می‌کند `drive.readonly` است. Google OAuth امکان scope مخصوص یک پوشه را ندارد؛ `drive.file` فقط فایل‌های ایجادشده/انتخاب‌شده برای برنامه را پوشش می‌دهد و برای این گردش کار کافی نیست. این محدودیت و restricted بودن scope در [مستندات رسمی scope](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) آمده است. برنامه query را به فرزندان مستقیم پوشه تنظیم‌شده محدود می‌کند و قبل و بعد از دانلود، تعلق فایل به پوشه و نسخه را بررسی می‌کند. پوشه‌های تو‌در‌تو و Google Vids/Workspace export در نسخه اول پشتیبانی نمی‌شوند؛ هدف فایل‌های ویدیویی باینری معمولی است.

همه صفحات `nextPageToken` خوانده می‌شوند؛ اسکن ناقص یا خطای یک صفحه، baseline را ثبت نمی‌کند. اولین اسکن کامل فقط فهرست می‌سازد، حتی اگر انتقال خودکار قبلاً روشن بوده باشد. برای فایل‌های قبلی انتخاب صریح مدیر لازم است. پس از اسکن اول انتقال خودکار را روشن کنید. فایل‌هایی که در زمان خاموش بودن کشف شده‌اند خودبه‌خود با روشن‌کردن گزینه صف نمی‌شوند. تغییر اتصال OAuth/پوشه، baseline تازه می‌خواهد. هنگام اتصال مجدد هیچ انتقال فعالی نباید در جریان باشد.

## Telegram و Local Bot API

طبق [مستندات رسمی Local Bot API](https://core.telegram.org/bots/api#using-a-local-bot-api-server)، حالت local فایل‌های تا ۲۰۰۰ مگابایت و مسیر محلی `file://` را می‌پذیرد. API عمومی برای این نیاز مناسب نیست. سقف برنامه پیش‌فرض ۵۰۰ MiB است و از ۲۰۰۰ MiB بالاتر پذیرفته نمی‌شود.

1. با حساب تلگرام خودتان وارد [my.telegram.org](https://my.telegram.org/) شوید؛ در **API development tools**، application بسازید و `api_id` و `api_hash` را دریافت کنید. این مقادیر متعلق به application هستند؛ **ربات جدید نسازید**. [راهنمای رسمی](https://core.telegram.org/api/obtaining_api_id).
2. `TELEGRAM_API_ID`، `TELEGRAM_API_HASH` و توکن همان `DriveGramOtiner_bot` را در `.env` بنویسید.
3. ربات را به کانال خصوصی مقصد اضافه کنید و با مجوز **Post Messages** مدیر کنید.
4. اگر ربات روی API عمومی استفاده می‌شده، برنامه قبلی آن را متوقف کنید و پیش از استفاده محلی logout کنید. این دستور تنها درخواست `logOut` را ارسال می‌کند و آدرس حاوی توکن را چاپ نمی‌کند:

   ```bash
   docker compose run --rm --no-deps app python scripts/telegram_admin.py cloud-logout
   ```

   پس از logout ورود محلی فوری ممکن است؛ ورود دوباره به cloud تا ۱۰ دقیقه ممکن نیست. این عملیات خودکار در startup انجام نمی‌شود. [مستندات logOut](https://core.telegram.org/bots/api#logout). اگر از یک Local Bot API دیگر جابه‌جا می‌شوید، روی سرور قدیمی `deleteWebhook` و سپس `close` را مطابق مستندات انجام دهید و هم‌زمان دو سرور برای این ربات اجرا نکنید.
5. سرویس Bot API را recreate کنید و در کانال یک پیام معمولی بفرستید. برای دریافت ID از updates:

   ```bash
   docker compose run --rm --no-deps app python scripts/telegram_admin.py channel-id
   ```

   خروجی فقط ID کانال‌هاست؛ مقدار مقصد معمولاً با `-100` آغاز می‌شود. اگر webhook قدیمی فعال است، getUpdates کار نمی‌کند؛ آن را در برنامه قبلی حذف کنید. ابزار channel-id صرفاً updates را می‌خواند و offset را جلو نمی‌برد.
6. `TELEGRAM_CHANNEL_ID` را وارد کرده و app/worker را recreate کنید. بررسی بدون ارسال پیام:

   ```bash
   docker compose run --rm --no-deps app python scripts/telegram_admin.py check
   ```

worker هر ۶۰ ثانیه `getMe`، نام کاربری دقیق ربات، نوع channel و مجوز ارسال را بررسی می‌کند. `TELEGRAM_BOT_API_URL` باید آدرس داخلی Local Bot API باشد. هیچ پورت Bot API یا دیتابیس روی میزبان منتشر نمی‌شود. worker و Bot API با UID مشترک و mount دقیقاً یکسان `/transfers` فایل را می‌خوانند؛ Bot API دسترسی read-only دارد. شبکه egress برای اتصال خروجی به Telegram/Google است. log خام Bot API غیرفعال است تا URL توکن‌دار ثبت نشود.

ffprobe فقط فایل را بررسی می‌کند و آن را تغییر نمی‌دهد. MP4 با H.264، صوت AAC/MP3 و `moov` قبل از `mdat` به صورت `sendVideo` با `supports_streaming=true` ارسال می‌شود. سایر فایل‌ها/codecها/MP4 بدون fast-start به صورت document ارسال می‌شوند. هیچ remux یا transcode انجام نمی‌شود؛ نام اصلی در کپشن plain text با سقف ۱۰۲۴ واحد UTF-16 ثبت می‌شود. نام فایل پیوست با حذف کاراکترهای خطرناک و حفظ پسوند اصلی استفاده می‌شود؛ نام کامل اصلی در کپشن باقی می‌ماند.

## رفتار صف و خطاها

`discovered → queued → downloading → uploading → completed`؛ خطاها به `failed` و لغو به `canceled` می‌روند. صف PostgreSQL پایدار است. claim داخل transaction با قفل ردیف control و `FOR UPDATE SKIP LOCKED` انجام می‌شود؛ تعداد انتقال‌های هم‌زمان **در کل workerها** با `MAX_CONCURRENT_TRANSFERS` محدود است، پیش‌فرض ۱.

کلید یکتا `(Drive file ID, content version)` است: MD5+size در صورت وجود، و در غیر آن `version` Drive. تغییر محتوا نسخه جدیدی می‌سازد و در حالت خودکار صف می‌شود؛ تغییر صرفاً نام/متادیتا با MD5 ثابت دوباره ارسال نمی‌شود. محتوای قدیمی که دیگر در Drive موجود نیست منتقل نمی‌شود؛ انتخاب آن `source_changed` می‌گیرد. انتقال موفق هر نسخه دوباره صف نمی‌شود. اندازه، MD5 و عضویت پوشه پیش/پس از دانلود بررسی می‌شوند.

دانلود با chunkهای ۱ MiB روی دیسک است. پیشرفت از تعداد بایت‌های واقعاً نوشته‌شده به دست می‌آید؛ آپلود فقط مرحله را نشان می‌دهد. timeout دانلود، خطای شبکه، فایل بیش از سقف، مجوز دانلود و فضای ذخیره مدیریت می‌شوند. قبل و حین دانلود فضای آزاد با `DISK_RESERVE_MB` بررسی می‌شود. فضای دیسک باید دانلودهای هم‌زمان **و cache سرور Bot API** را پوشش دهد.

خطاهای موقت با exponential backoff، jitter و حداکثر `MAX_ATTEMPTS` تلاش می‌شوند. `Retry-After` گوگل و `retry_after` تلگرام رعایت می‌شوند؛ 429 تلگرام همه claimهای بعدی را تا پایان مهلت متوقف می‌کند. lease و heartbeat مانع سرقت کار worker زنده می‌شوند. پس از قطع worker، دانلود منقضی‌شده دوباره صف می‌شود؛ آپلود منقضی‌شده **برای بررسی دستی** failed می‌شود. قطع شبکه پس از آغاز ارسال، پاسخ نامعتبر، خطای 5xx ارسال یا موفقیت با ذخیره‌سازی ناموفق در DB ممکن است پیام تولید کرده باشند؛ هیچ retry خودکاری برای آن‌ها انجام نمی‌شود. Bot API کلید idempotency برای ارسال پیام ندارد؛ تضمین exactly-once بین دو سرویس ممکن نیست.

برای نتیجه نامشخص، ابتدا کانال و پایان پردازش Local Bot API را بررسی کنید؛ سپس در پنل «بستن بررسی بدون ارسال» یا با تأیید عدم وجود پیام «ارسال پس از بررسی» را انتخاب کنید. فایل موقت نامشخص تا این تصمیم باقی می‌ماند تا حذف آن وسط پردازش Bot API رخ ندهد. بستن بررسی فایل را پاک می‌کند و کار canceled باقی می‌ماند؛ وضعیت completed با پیام تأییدنشده ساخته نمی‌شود. لغو هنگام دانلود تعاونی است؛ هنگام uploading لغو امن رد می‌شود. پس از موفقیت، خطای قطعی یا لغو، فایل موقت پاک می‌شود؛ janitor پوشه‌های باقی‌مانده پس از restart را نیز پاک می‌کند. حذف cache داخلی Bot API هنگام فعال‌بودن آن توصیه نمی‌شود.

## تنظیمات و امنیت

| متغیر | کاربرد |
|---|---|
| `POLL_INTERVAL_SECONDS=60` | فاصله اسکن، حداقل ۱۰ ثانیه |
| `MAX_FILE_SIZE_MB=500` | سقف فایل، واحد MiB |
| `MAX_CONCURRENT_TRANSFERS=1` | محدودیت سراسری هم‌زمانی |
| `MAX_ATTEMPTS=5`, `RETRY_BASE_SECONDS=30` | سقف تلاش و پایه backoff |
| `DOWNLOAD_TIMEOUT_SECONDS=1800`, `UPLOAD_TIMEOUT_SECONDS=3600` | مهلت دانلود/پاسخ آپلود |
| `LEASE_SECONDS=120` | lease؛ heartbeat مستقل هر حداکثر ۱۰ ثانیه |
| `DISK_RESERVE_MB=512` | فضای رزرو قبل و حین دانلود |
| `TOKEN_ENCRYPTION_KEY` | کلید Fernet؛ جدا از DB نگهداری و backup شود |
| `SESSION_SECRET` | secret حداقل ۳۲ کاراکتر؛ تعویض آن همه سشن‌ها را باطل می‌کند |
| `ADMIN_PASSWORD_HASH` | Argon2 hash اختیاری با اولویت بر رمز plaintext |
| `COOKIE_SECURE` | روی HTTPS برابر true |
| `PANEL_BIND=127.0.0.1:8000` | binding محلی پشت reverse proxy |

رمز محیط در startup به Argon2 hash تبدیل می‌شود و verification با hash است؛ plaintext در DB ذخیره نمی‌شود. تغییر رمز: مقدار `ADMIN_PASSWORD` یا hash را در `.env` تغییر دهید و app را recreate کنید؛ سشن‌های قبلی با fingerprint مبتنی بر HMAC باطل می‌شوند. برای ساخت hash، داخل محیط نصب‌شده دستور زیر را اجرا کنید؛ رمز در ورودی مخفی گرفته می‌شود و خروجی **hash** است:

```bash
python -c "from argon2 import PasswordHasher; from getpass import getpass; print(PasswordHasher().hash(getpass('New password: ')))"
```

مقدار hash را در `.env` داخل کوتیشن تکی قرار دهید (`ADMIN_PASSWORD_HASH='…'`) تا Docker Compose علامت‌های `$` آن را جایگزین متغیر محیطی نکند.

پنل از cookie امضاشده با HttpOnly، SameSite و انقضای ۸ ساعته، CSRF برای عملیات تغییردهنده، throttling پایدار ورود (۵ تلاش ناموفق در ۱۵ دقیقه) و CSP استفاده می‌کند. مقادیر محرمانه در پاسخ پنل نیستند. access log اپ غیرفعال است؛ errorها و logهای worker متن ثابت و شناسه کار دارند. نام‌های Drive با `textContent` نمایش داده می‌شوند؛ پوشه فایل فقط UUID تولیدشده سرور است و نام فایل اعتبارسنجی و کوتاه می‌شود. URL دلخواه برای دانلود وجود ندارد.

در Linux `.env` را با permission 600 نگه دارید. در Windows دسترسی NTFS پوشه پروژه و `.env` را به حساب خودتان محدود کنید. `.env`، backup، dump، cache و محیط Python در git و build context قرار نمی‌گیرند. خروجی `docker inspect` و ابزارهای مدیریت فرایندها ممکن است env را به مدیر سیستم نشان دهند؛ به افراد غیرمدیر دسترسی Docker ندهید.

## استقرار HTTPS روی Linux

سرور خارج از ایران، domain و DNS صحیح آماده کنید. Caddy یا Nginx روی میزبان به `127.0.0.1:8000` proxy کند؛ نمونه Caddy در `docker/Caddyfile.example` است. پورت‌های 80/443 را برای reverse proxy باز کنید؛ 8000، 5432 و 8081 عمومی نشوند. `PUBLIC_BASE_URL` را آدرس HTTPS، `GOOGLE_REDIRECT_URI` را callback همان domain و `COOKIE_SECURE=true` بگذارید. access log reverse proxy برای callback OAuth باید غیرفعال یا query string آن حذف شود. `PUBLIC_BASE_URL` برای مستندسازی origin است؛ اپ از forwarded headers برای ساخت URL امنیتی استفاده نمی‌کند.

Windows برای توسعه با Docker Desktop/WSL2 و Linux containers مناسب است. daemon باید در حال اجرا باشد؛ خطای named pipe یعنی Docker Engine در دسترس نیست. برای اجرای پایدار روی Linux از volumeهای named و restart policy استفاده کنید. کانتینرها غیر-root هستند؛ فایل‌های bind-mounted قبلی باید مالک UID 10001 باشند. در نسخه اول TLS در reverse proxy خاتمه می‌یابد.

## تست‌ها

```bash
pip install -r requirements.lock
pip install -e '.[test]'
ruff check .
pytest -q
```

پیش‌فرض SQLite فقط برای تست‌های mock است؛ تست `FOR UPDATE` به PostgreSQL واقعی نیاز دارد و بدون آن **skip** می‌شود. در PowerShell:

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/drivegram_test'
.\.venv\Scripts\python.exe -m pytest -q
```

در Linux:

```bash
TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/drivegram_test' pytest -q
```

از دیتابیس تست استفاده کنید. fixture برای هر تست schema تصادفی ایجاد و فقط همان را پاک می‌کند؛ role باید مجوز CREATE schema داشته باشد. CI، PostgreSQL واقعی، migration، بررسی drift، تست‌ها و build اپ را اجرا می‌کند. هیچ تست mock به حساب Google/Telegram واقعی درخواست نمی‌فرستد. تست‌های claim با ۸ worker رقیب، منع تکرار، restart، retry_after، cancellation، صف پایدار، encryption، OAuth state، CSRF و پاک‌سازی را پوشش می‌دهند.

**تست پذیرش واقعی** فقط بعد از تکمیل تنظیمات: یک ویدیوی آزمایشی ۳۰۰ MiB در پوشه خصوصی قرار دهید؛ اسکن اول را ببینید، دستی انتخاب و منتقل کنید؛ نام، اندازه/checksum و کیفیت فایل دریافتی تلگرام را بررسی کنید. rescan و restart نباید دوباره همان نسخه را ارسال کنند. برای شبکه قطع‌شده و آپلود نامشخص رفتار review را بررسی کنید. فایل اصلی باید در Drive باقی بماند. این تست بدون credentials معتبر تأییدشده محسوب نمی‌شود.

## پشتیبان‌گیری و بازیابی

volumeهای `postgres-data`، `bot-api-data` و `transfers` پایدارند. توقف معمول `docker compose down` آن‌ها را نگه می‌دارد؛ **`down -v` داده‌ها را حذف می‌کند**. یک backup رمزگذاری‌شده از `.env` (به‌ویژه کلید Fernet و secretها) جدا از dump بگیرید؛ بدون کلید، refresh token قابل بازیابی نیست.

برای backup سازگار، worker را متوقف کنید و از داخل کانتینر dump بگیرید؛ این روش خرابی فایل باینری با redirect در PowerShell قدیمی را هم دور می‌زند:

```bash
docker compose stop worker
docker compose exec -T db pg_dump -U drivegram -d drivegram -Fc -f /tmp/drivegram.dump
docker compose cp db:/tmp/drivegram.dump ./backups/drivegram.dump
docker compose exec -T db rm /tmp/drivegram.dump
docker compose start worker
```

قبل از copy پوشه `backups` را بسازید. توقف حین uploading ممکن است review بسازد؛ بهتر است ابتدا منتظر پایان انتقال‌ها بمانید. در مقصد ابتدا `.env` را امن بازیابی کنید، `db` را بالا بیاورید، dump را به آن copy کنید و سپس فقط روی دیتابیس خالی بازیابی کنید:

```bash
docker compose up -d db
docker compose cp ./backups/drivegram.dump db:/tmp/drivegram.dump
docker compose exec -T db pg_restore -U drivegram -d drivegram --no-owner /tmp/drivegram.dump
docker compose exec -T db rm /tmp/drivegram.dump
docker compose up -d --build
```

برای مقصد دارای داده ابتدا backup مستقل بگیرید؛ دستور پاک‌کردن خودکار DB ارائه نشده است. `alembic_version` در dump هست. Bot API قدیمی را پیش از جابه‌جایی متوقف کنید؛ volume آن را فقط هنگام توقف backup کنید. صف بازیابی‌شده دانلودهای منقضی را retry و آپلودهای منقضی را review می‌کند؛ همیشه کانال را با وضعیت DB تطبیق دهید. تغییر کلید Fernet بدون رمزگشایی/رمزگذاری مجدد، اتصال ذخیره‌شده را از کار می‌اندازد؛ در آن حالت OAuth را دوباره برقرار کنید.

## محدودیت‌های نسخه اول

یک مدیر، یک پوشه (فقط فایل‌های مستقیم) و یک کانال؛ بدون پرداخت، چندمستاجری، حذف مبدا، دانلود URL ناشناس یا تبدیل ویدیو. ارسال document برای سازگاری نامطمئن intentional است. لینک `t.me/c/...` فقط برای اعضای کانال خصوصی باز می‌شود. مراحل real-connect در نبود تنظیمات قابل تأیید نیستند؛ پنل وضعیت تنظیم اتصال را صادقانه نمایش می‌دهد.

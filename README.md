# ربات تلگرامی تخمین تراز سوابق و کنکور ۱۴۰۴ (رشته تجربی)

این ربات دقیقاً همون منطق فایل اکسل `taraz_estimator` رو پیاده‌سازی می‌کنه:
جست‌وجو و درون‌یابی (interpolation) در جدول واقعی کارنامه‌های ۱۴۰۴، و میانگین وزنی
با ضرایب رسمی سوابق/کنکور.

ورودی هر بخش **یک‌جا** گرفته می‌شه — درست مثل پر کردن یک ستون توی اکسل: ربات
لیست درس‌ها رو با ترتیب و ضریبشون نشون می‌ده، و دانش‌آموز همه‌ی نمره‌ها یا
درصدها رو با فاصله یا کاما، توی یک پیام، پشت سر هم می‌فرسته.

## فایل‌ها
- `taraz_bot.py` — کد اصلی ربات
- `taraz_data.json` — همون جدول‌های `Data_Sawabegh` و `Data_Konkur` که از اکسل استخراج شده
- `requirements.txt`, `Procfile`, `railway.json`, `.gitignore` — فایل‌های پیکربندی دیپلوی

> نکته: اسم این ۴ تای آخر (`requirements.txt`, `Procfile`, `railway.json`, `.gitignore`)
> استاندارد و ثابته — پایتون، گیت و Railway دقیقاً با همین اسم‌ها دنبالشون می‌گردن،
> پس عمداً تغییرشون ندادیم. فقط دو فایل خودمون (`taraz_bot.py` و `taraz_data.json`)
> با پیشوند `taraz_` هم‌شکل شدن تا راحت‌تر پیدا بشن.

## قدم ۱: ساخت ربات در تلگرام
1. تو تلگرام به [@BotFather](https://t.me/BotFather) پیام بده.
2. دستور `/newbot` رو بزن و اسم/یوزرنیم دلخواه بده.
3. یک **توکن** بهت می‌ده، چیزی شبیه `123456:ABC-DEF...`. این رو نگه دار (جایی share نکن).

## قدم ۲: تست محلی (اختیاری)
```bash
python -m venv venv
source venv/bin/activate      # ویندوز: venv\Scripts\activate
pip install -r requirements.txt
export BOT_TOKEN="توکنی که از BotFather گرفتی"   # ویندوز: set BOT_TOKEN=...
python taraz_bot.py
```
حالا تو تلگرام به ربات `/start` بزن.

## قدم ۳: آپلود روی گیت‌هاب
```bash
git init
git add .
git commit -m "taraz estimator telegram bot"
git branch -M main
git remote add origin https://github.com/USERNAME/REPO_NAME.git
git push -u origin main
```
(⚠️ توکن ربات رو هیچ‌وقت داخل کد یا commit قرار نده — همیشه از environment variable استفاده کن؛ `.gitignore` هم `.env` رو نادیده می‌گیره.)

## قدم ۴: دیپلوی روی Railway
1. وارد [railway.app](https://railway.app) شو و با گیت‌هابت لاگین کن.
2. **New Project → Deploy from GitHub repo** و ریپوی همین پروژه رو انتخاب کن.
3. Railway به‌صورت خودکار `railway.json` / `Procfile` رو تشخیص می‌ده و `python taraz_bot.py` رو اجرا می‌کنه.
4. برو به تب **Variables** و یک متغیر اضافه کن:
   - Key: `BOT_TOKEN`
   - Value: توکنی که از BotFather گرفتی
5. Deploy رو بزن. تو تب **Logs** باید ببینی `Bot starting (polling)...`.
6. حالا برو تو تلگرام و به ربات `/start` بزن.

> این ربات با «polling» کار می‌کنه (نه webhook)، پس نیازی به دامنه یا HTTPS نداری —
> فقط کافیه پروسه همیشه روشن بمونه، که روی Railway به‌صورت پیش‌فرض همینه.

## نکات محاسباتی (برای شفافیت)
- تراز هر درس از روی جدول واقعی کارنامه‌ها (نه فرمول آماری) با درون‌یابی خطی به دست میاد.
- تراز سوابق = میانگین وزنی تراز ۱۰ درس با ضرایب رسمی سوابق.
- تراز کنکور (اختصاصی) = میانگین وزنی تراز ۴ یا ۵ درس تخصصی؛ زمین‌شناسی اختیاریه.
- تراز نهایی = ۶۰٪ سوابق + ۴۰٪ کنکور اختصاصی (طبق سهم اعلامی ۱۴۰۴)، بدون احتساب دروس عمومی حذف‌شده — این عدد صرفاً یک تخمینه.

## به‌روزرسانی داده‌ها در آینده
اگه بعداً جدول‌های منبع (کارنامه‌های واقعی) به‌روز شدن، کافیه `taraz_data.json` رو با
داده‌ی تازه جایگزین کنی؛ ساختار باید همون کلیدهای `sawabegh_headers`,
`sawabegh`, `konkur_headers`, `konkur` رو حفظ کنه.

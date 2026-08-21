# -*- coding: utf-8 -*-
"""
ربات تلگرامی «تخمین تراز سوابق تحصیلی و کنکور ۱۴۰۴ - رشته تجربی»

منطق این ربات دقیقاً بر اساس فرمول‌های اکسل taraz_estimator است:
- جست‌وجوی خطی (lookup + interpolation) در جدول‌های واقعی کارنامه‌ها
- میانگین وزنی با ضرایب رسمی
- ترکیب نهایی سوابق/کنکور طبق سهم ۶۰٪ / ۴۰٪ اعلامی سال ۱۴۰۴
- بازه‌ی تخمینی «خوش‌بینانه» حول هر عدد نهایی (چون کنکور ۱۴۰۴ سخت بوده و
  خیلی از داوطلب‌ها درصد پایین‌تری نسبت به سال‌های قبل زدن)

هر درس در یک پیام جداگانه پرسیده می‌شه (نه یک‌جا)، و فقط نتیجه‌ی نهایی
(بدون ریز تراز هر درس) نمایش داده می‌شه.

امکانات ادمین:
- کاربرها می‌تونن از دکمه‌ی «ارسال پیام به پشتیبانی» برای ادمین پیام بفرستن.
- ادمین با دستور /broadcast <متن> می‌تونه به همه‌ی کاربرهایی که تا حالا /start
  زدن، یه پیام (مثلاً تبلیغ کانال) بفرسته.
- دستور /myid به هرکسی شناسه‌ی عددی خودش رو نشون می‌ده (برای گرفتن ADMIN_ID).

نکته‌ی بعدی که در دست ساختنه: تخمین رتبه (بر اساس فایل تبدیل تراز-به-رتبه
که قراره جداگانه اضافه بشه) — فعلاً فقط تراز نهایی نمایش داده می‌شه.
"""

import json
import logging
import os
import re
from pathlib import Path

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).parent / "taraz_data.json"
with open(DATA_PATH, "r", encoding="utf-8") as f:
    DATA = json.load(f)

USERS_PATH = Path(__file__).parent / "users.json"
CONTACT_MAP_PATH = Path(__file__).parent / "contact_map.json"

ADMIN_ID = int(os.environ.get("ADMIN_ID", "0") or "0")

# ---------------------------------------------------------------------------
# تعریف درس‌ها (دقیقاً مطابق دو شیت اکسل)
# هر آیتم: (نام نمایشی, ضریب رسمی, ایندکس ستون در جدول Data_*)
# ---------------------------------------------------------------------------

SAWABEGH_SUBJECTS = [
    ("ادبیات فارسی ۳", 11.09, 1),
    ("عربی، زبان قرآن ۳", 4.64, 2),
    ("دینی ۳", 8.47, 3),
    ("زبان انگلیسی ۳", 6.05, 4),
    ("سلامت و بهداشت", 1.76, 5),
    ("علوم اجتماعی", 1.31, 6),
    ("زیست‌شناسی ۳", 11.45, 7),
    ("ریاضی ۳", 6.55, 8),
    ("فیزیک ۳", 5.90, 9),
    ("شیمی ۳", 9.44, 10),
]

KONKUR_SUBJECTS = [
    ("زیست‌شناسی", 12, 1, True),
    ("شیمی", 9, 2, True),
    ("فیزیک", 7, 3, True),
    ("ریاضی", 7, 4, True),
    ("زمین‌شناسی", 1, 5, False),  # اختیاری
]

SAWABEGH_TABLE = DATA["sawabegh"]  # هر ردیف: [نمره, ادبیات, عربی, ..., شیمی]
KONKUR_TABLE = DATA["konkur"]  # هر ردیف: [درصد, زیست, شیمی, فیزیک, ریاضی, زمین]

# جدول‌های تراز-به-رتبه (اختیاری) — هر ردیف [تراز, رتبه]، صعودی بر اساس تراز
RANK_TABLES = DATA.get("rank_by_region", {})
REGION_LABELS = {
    "region1": "منطقه ۱",
    "region2": "منطقه ۲",
    "region3": "منطقه ۳",
}

SAWABEGH_MIN_GRADE = SAWABEGH_TABLE[0][0]  # کوچیک‌ترین نمره‌ای که جدول پوشش می‌ده

SAWABEGH_RECORDS_SHARE = 0.60  # سهم رسمی سوابق تحصیلی در ۱۴۰۴
KONKUR_SPECIALIZED_SHARE = 0.40  # سهم دروس تخصصی کنکور

# بازه‌ی تخمینی حول هر عدد نهایی — «خوش‌بینانه»: سمت پایین بازه رو کمتر و
# سمت بالا رو بیشتر می‌کشیم، چون کنکور ۱۴۰۴ سخت بوده و درصدهای عمومی پایین‌تر
# از سال‌های قبل بوده.
SAWABEGH_MARGIN_PERCENT = 0.025  # ±۲.۵٪ پایه
KONKUR_MARGIN_PERCENT = 0.035    # ±۳.۵٪ پایه
FINAL_MARGIN_PERCENT = 0.035     # ±۳.۵٪ پایه
OPTIMISM_SKEW = 0.4              # هرچه بیشتر، بازه بیشتر به سمت بالا کشیده می‌شه

# فارسی/عربی -> ارقام لاتین، برای اینکه هرجور کاربر عدد را تایپ کند بخوانیم
DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
)

SKIP_TOKENS = {"-", "_", "x", "X", "ندادم", "رد", "خالی", "skip", "none", ""}

# ---------------------------------------------------------------------------
# حالت‌های مکالمه
# ---------------------------------------------------------------------------
MAIN_MENU, SAWABEGH_Q, KONKUR_Q, CONTACT_INPUT, REGION_Q = range(5)

MENU_SAWABEGH = "📚 تراز سوابق تحصیلی"
MENU_KONKUR = "📝 تراز کنکور (اختصاصی)"
MENU_BOTH = "🎯 هردو + تراز نهایی"
MENU_CONTACT = "✉️ ارسال پیام به پشتیبانی"
MENU_CANCEL = "لغو"
SKIP_TEXT = "رد شدن (امتحان نداده‌ام)"

MENU_REGION_1 = "🟢 منطقه ۱"
MENU_REGION_2 = "🟡 منطقه ۲"
MENU_REGION_3 = "🔵 منطقه ۳"
REGION_BUTTON_MAP = {
    MENU_REGION_1: "region1",
    MENU_REGION_2: "region2",
    MENU_REGION_3: "region3",
}


# ---------------------------------------------------------------------------
# ذخیره‌ی ساده‌ی کاربرها (برای Broadcast)
# توجه: این فایل روی دیسک همون کانتینره؛ با هر Redeploy ممکنه پاک بشه مگر
# اینکه یه Volume روی Railway بهش وصل کنی.
# ---------------------------------------------------------------------------

def load_users() -> set:
    if not USERS_PATH.exists():
        return set()
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def save_users(users: set):
    try:
        with open(USERS_PATH, "w", encoding="utf-8") as f:
            json.dump(sorted(users), f)
    except OSError as e:
        logger.warning("Could not save users.json: %s", e)


def register_user(update: Update):
    if not update.effective_user:
        return
    users = load_users()
    uid = update.effective_user.id
    if uid not in users:
        users.add(uid)
        save_users(users)


def load_contact_map() -> dict:
    """نگاشت شناسه‌ی پیامی که برای ادمین فوروارد شده -> شناسه‌ی چت کاربر اصلی.
    این باعث می‌شه وقتی ادمین روی پیام فوروارد‌شده Reply می‌زنه، بدونیم جوابش
    باید برای کدوم کاربر برگرده."""
    if not CONTACT_MAP_PATH.exists():
        return {}
    try:
        with open(CONTACT_MAP_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_contact_map(mapping: dict):
    try:
        with open(CONTACT_MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False)
    except OSError as e:
        logger.warning("Could not save contact_map.json: %s", e)


def parse_number(token: str):
    """عدد فارسی/انگلیسی را به float تبدیل می‌کند، یا None برمی‌گرداند."""
    cleaned = token.strip().translate(DIGIT_MAP)
    cleaned = cleaned.replace(",", ".").replace("٫", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def interpolate(table, col_index: int, x: float) -> float:
    """
    دقیقاً معادل فرمول اکسل:
    IF(x<=first_key, first_value,
       IF(x>=last_key, last_value,
          interpolation خطی بین دو نقطه‌ی همسایه))
    """
    keys = [row[0] for row in table]
    if x <= keys[0]:
        return table[0][col_index]
    if x >= keys[-1]:
        return table[-1][col_index]
    for i in range(len(keys) - 1):
        x0, x1 = keys[i], keys[i + 1]
        if x0 <= x <= x1:
            y0, y1 = table[i][col_index], table[i + 1][col_index]
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][col_index]


def taraz_range_values(value: int, percent: float):
    """
    بازه‌ی تخمینی «خوش‌بینانه» حول یک عدد نهایی: سمت پایین کوچیک‌تر، سمت بالا
    بزرگ‌تر (چون کنکور امسال سخت بوده و کف تراز واقعی معمولاً بالاتر از
    محاسبه‌ی خام درمیاد). خروجی: (پایین, بالا)
    """
    margin = value * percent
    low = round(value - margin * (1 - OPTIMISM_SKEW))
    high = round(value + margin * (1 + OPTIMISM_SKEW))
    return low, high


def format_range(low: int, high: int) -> str:
    return f"{low:,} تا {high:,}".replace(",", "٬")


def range_text(value: int, percent: float) -> str:
    low, high = taraz_range_values(value, percent)
    return format_range(low, high)


def region_keyboard():
    return ReplyKeyboardMarkup(
        [[MENU_REGION_1], [MENU_REGION_2], [MENU_REGION_3], [MENU_CANCEL]],
        resize_keyboard=True,
    )


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[MENU_SAWABEGH], [MENU_KONKUR], [MENU_BOTH], [MENU_CONTACT], [MENU_CANCEL]],
        resize_keyboard=True,
    )


def cancel_keyboard(extra_skip: bool = False):
    rows = [[MENU_CANCEL]]
    if extra_skip:
        rows.insert(0, [SKIP_TEXT])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ---------------------------------------------------------------------------
# شروع / منو
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    register_user(update)
    context.user_data.clear()
    await update.message.reply_text(
        "سلام 👋\n"
        "این ربات تراز تخمینی سوابق تحصیلی و کنکور ۱۴۰۵ (رشته تجربی) رو بر اساس "
        "جدول واقعی کارنامه‌های ۱۴۰۴ حساب می‌کنه.\n\n"
        "یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=main_menu_keyboard(),
    )
    return MAIN_MENU


async def menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == MENU_SAWABEGH:
        return await start_sawabegh(update, context, then_konkur=False)
    if text == MENU_KONKUR:
        return await start_konkur(update, context, combine=False)
    if text == MENU_BOTH:
        return await start_sawabegh(update, context, then_konkur=True)
    if text == MENU_CONTACT:
        return await prompt_contact(update, context)
    if text == MENU_CANCEL:
        return await cancel(update, context)
    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های روی صفحه‌کلید رو انتخاب کن.",
        reply_markup=main_menu_keyboard(),
    )
    return MAIN_MENU


# ---------------------------------------------------------------------------
# مسیر سوابق تحصیلی — هر درس در یک پیام جداگانه
# ---------------------------------------------------------------------------
async def start_sawabegh(update: Update, context: ContextTypes.DEFAULT_TYPE, then_konkur: bool) -> int:
    context.user_data["saw_index"] = 0
    context.user_data["saw_scores"] = {}
    context.user_data["then_konkur"] = then_konkur
    await update.message.reply_text(
        f"نمره‌ی نهایی هر درس رو بین {SAWABEGH_MIN_GRADE:g} تا ۲۰ وارد کن.",
        reply_markup=cancel_keyboard(),
    )
    await ask_next_sawabegh(update, context)
    return SAWABEGH_Q


async def ask_next_sawabegh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data["saw_index"]
    name, coeff, _col = SAWABEGH_SUBJECTS[idx]
    await update.message.reply_text(f"نمره‌ی «{name}» (ضریب {coeff}) چنده؟")


async def handle_sawabegh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == MENU_CANCEL:
        return await cancel(update, context)

    idx = context.user_data["saw_index"]
    name, coeff, col = SAWABEGH_SUBJECTS[idx]
    value = parse_number(text)
    if value is None:
        await update.message.reply_text("یه عدد معتبر بفرست، مثلاً 17.5")
        return SAWABEGH_Q
    if value < 0 or value > 20:
        await update.message.reply_text("نمره باید بین ۰ تا ۲۰ باشه. دوباره وارد کن:")
        return SAWABEGH_Q
    if value < SAWABEGH_MIN_GRADE:
        await update.message.reply_text(
            f"⚠️ توجه: جدول منبع فقط از نمره‌ی {SAWABEGH_MIN_GRADE:g} به بالا رو پوشش می‌ده، "
            "برای این نمره دقت مدل کمتره."
        )

    context.user_data["saw_scores"][idx] = value
    context.user_data["saw_index"] += 1

    if context.user_data["saw_index"] < len(SAWABEGH_SUBJECTS):
        await ask_next_sawabegh(update, context)
        return SAWABEGH_Q

    result = compute_sawabegh(context.user_data["saw_scores"])
    context.user_data["saw_result"] = result
    await update.message.reply_text(
        f"✅ تراز تخمینی سوابق تحصیلی: {result['final']:.0f}\n"
        f"📊 بازه‌ی تخمینی: {range_text(result['final'], SAWABEGH_MARGIN_PERCENT)}"
    )

    if context.user_data.get("then_konkur"):
        return await start_konkur(update, context, combine=True)

    await update.message.reply_text(
        "برای شروع دوباره /start رو بزن.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


def compute_sawabegh(scores: dict) -> dict:
    per_subject = []
    for i, (name, coeff, col) in enumerate(SAWABEGH_SUBJECTS):
        val = interpolate(SAWABEGH_TABLE, col, scores[i])
        per_subject.append(val)
    total_coeff = sum(c for _n, c, _c in SAWABEGH_SUBJECTS)
    weighted = sum(c * v for (_n, c, _c), v in zip(SAWABEGH_SUBJECTS, per_subject))
    final = round(weighted / total_coeff)
    return {"per_subject": per_subject, "final": final}


# ---------------------------------------------------------------------------
# مسیر کنکور — هر درس در یک پیام جداگانه
# ---------------------------------------------------------------------------
async def start_konkur(update: Update, context: ContextTypes.DEFAULT_TYPE, combine: bool) -> int:
    context.user_data["kon_index"] = 0
    context.user_data["kon_scores"] = {}
    context.user_data["combine"] = combine
    await update.message.reply_text(
        "درصد تراز خودت رو تو هر درس تخصصی وارد کن (از منفی ۵ تا ۱۰۰).",
        reply_markup=cancel_keyboard(),
    )
    await ask_next_konkur(update, context)
    return KONKUR_Q


async def ask_next_konkur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data["kon_index"]
    name, coeff, _col, required = KONKUR_SUBJECTS[idx]
    optional_note = "" if required else " (اگه امتحان ندادی رد شدن رو بزن)"
    await update.message.reply_text(
        f"درصد «{name}» (ضریب {coeff}) چنده؟{optional_note}",
        reply_markup=cancel_keyboard(extra_skip=not required),
    )


async def handle_konkur(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == MENU_CANCEL:
        return await cancel(update, context)

    idx = context.user_data["kon_index"]
    name, coeff, col, required = KONKUR_SUBJECTS[idx]

    if text == SKIP_TEXT and not required:
        context.user_data["kon_scores"][idx] = None
    else:
        value = parse_number(text)
        if value is None:
            await update.message.reply_text("یه عدد معتبر بفرست، مثلاً 45")
            return KONKUR_Q
        if value < -5 or value > 100:
            await update.message.reply_text("درصد باید بین ۵- تا ۱۰۰ باشه. دوباره وارد کن:")
            return KONKUR_Q
        context.user_data["kon_scores"][idx] = value

    context.user_data["kon_index"] += 1

    if context.user_data["kon_index"] < len(KONKUR_SUBJECTS):
        await ask_next_konkur(update, context)
        return KONKUR_Q

    filled = sum(1 for v in context.user_data["kon_scores"].values() if v is not None)
    if filled < 4:
        await update.message.reply_text(
            "حداقل باید ۴ درس اصلی رو وارد کنی. بیا از اول این بخش شروع کنیم."
        )
        return await start_konkur(update, context, combine=context.user_data.get("combine", False))

    result = compute_konkur(context.user_data["kon_scores"])
    context.user_data["kon_result"] = result
    await update.message.reply_text(
        f"✅ تراز تخمینی کنکور (اختصاصی): {result['final']:.0f}\n"
        f"📊 بازه‌ی تخمینی: {range_text(result['final'], KONKUR_MARGIN_PERCENT)}"
    )

    if context.user_data.get("combine") and "saw_result" in context.user_data:
        next_state = await send_final_combination(update, context)
        if next_state == REGION_Q:
            return REGION_Q

    await update.message.reply_text(
        "برای شروع دوباره /start رو بزن.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


def compute_konkur(scores: dict) -> dict:
    per_subject = []
    weighted = 0.0
    coeff_used = 0.0
    for i, (name, coeff, col, _req) in enumerate(KONKUR_SUBJECTS):
        v = scores[i]
        if v is None:
            per_subject.append(None)
            continue
        val = interpolate(KONKUR_TABLE, col, v)
        per_subject.append(val)
        weighted += coeff * val
        coeff_used += coeff
    final = round(weighted / coeff_used) if coeff_used else 0
    return {"per_subject": per_subject, "final": final}


async def send_final_combination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نتیجه‌ی نهایی رو می‌فرسته؛ اگه داده‌ی رتبه موجود باشه، REGION_Q برمی‌گردونه
    تا از کاربر منطقه‌ی کنکورش رو بپرسه، وگرنه None."""
    saw_final = context.user_data["saw_result"]["final"]
    kon_final = context.user_data["kon_result"]["final"]
    combined = round(
        SAWABEGH_RECORDS_SHARE * saw_final + KONKUR_SPECIALIZED_SHARE * kon_final
    )
    low, high = taraz_range_values(combined, FINAL_MARGIN_PERCENT)
    context.user_data["final_taraz_range"] = (low, high)

    await update.message.reply_text(
        "———————————\n"
        f"🏁 تراز نهایی تخمینی: {combined}\n"
        f"📊 بازه‌ی تخمینی: {format_range(low, high)}\n\n"
        "⚠️ این عدد فقط یه تخمینه؛ سهم دروس عمومی کنکور در این محاسبه لحاظ نشده "
        "چون طبق تغییرات ۱۴۰۴ حذف شدن."
    )

    if RANK_TABLES:
        await update.message.reply_text(
            "برای گرفتن بازه‌ی رتبه‌ی تخمینی، منطقه‌ی کنکورت رو انتخاب کن:",
            reply_markup=region_keyboard(),
        )
        return REGION_Q
    return None


async def handle_region(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == MENU_CANCEL:
        return await cancel(update, context)

    region_key = REGION_BUTTON_MAP.get(text)
    if not region_key:
        await update.message.reply_text(
            "لطفاً یکی از گزینه‌های منطقه رو از روی صفحه‌کلید انتخاب کن.",
            reply_markup=region_keyboard(),
        )
        return REGION_Q

    low, high = context.user_data.get("final_taraz_range", (None, None))
    table = RANK_TABLES.get(region_key)
    if low is None or not table:
        await update.message.reply_text(
            "⚠️ داده‌ی رتبه برای این حالت موجود نیست.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        # چون تراز بالاتر یعنی رتبه‌ی بهتر (عدد کوچیک‌تر)، بازه‌ی تراز رو
        # به بازه‌ی رتبه معکوس می‌کنیم.
        best_rank = round(interpolate(table, 1, high))
        worst_rank = round(interpolate(table, 1, low))
        if best_rank > worst_rank:
            best_rank, worst_rank = worst_rank, best_rank
        await update.message.reply_text(
            f"🏅 رتبه‌ی تخمینی در {REGION_LABELS.get(region_key, region_key)}: "
            f"{format_range(best_rank, worst_rank)}\n\n"
            "⚠️ این بازه هم بر اساس کارنامه‌های واقعی همون تراز به‌دست اومده و صرفاً یک تخمینه.",
            reply_markup=ReplyKeyboardRemove(),
        )

    await update.message.reply_text("برای شروع دوباره /start رو بزن.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# پیام به پشتیبانی (فوروارد برای ادمین)
# ---------------------------------------------------------------------------
async def prompt_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "پیامتو بنویس و بفرست، مستقیم برای پشتیبانی ارسال می‌شه.",
        reply_markup=cancel_keyboard(),
    )
    return CONTACT_INPUT


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == MENU_CANCEL:
        return await cancel(update, context)

    if not ADMIN_ID:
        await update.message.reply_text(
            "⚠️ شناسه‌ی ادمین هنوز تنظیم نشده، پیامت الان قابل ارسال نیست.",
            reply_markup=main_menu_keyboard(),
        )
        return MAIN_MENU

    user = update.effective_user
    username = f"@{user.username}" if user.username else "(بدون یوزرنیم)"
    admin_text = (
        f"✉️ پیام جدید از کاربر:\n"
        f"نام: {user.full_name}\n"
        f"یوزرنیم: {username}\n"
        f"شناسه: {user.id}\n\n"
        f"متن پیام:\n{text}"
    )
    try:
        sent = await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text)
        # این نگاشت رو ذخیره می‌کنیم تا اگه ادمین روی همین پیام Reply بزنه،
        # بدونیم جوابش باید برای همین کاربر برگرده.
        mapping = load_contact_map()
        mapping[str(sent.message_id)] = user.id
        save_contact_map(mapping)
        await update.message.reply_text(
            "✅ پیامت برای پشتیبانی ارسال شد.", reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        logger.warning("Could not forward message to admin: %s", e)
        await update.message.reply_text(
            "⚠️ مشکلی تو ارسال پیش اومد، بعداً دوباره امتحان کن.",
            reply_markup=main_menu_keyboard(),
        )
    return MAIN_MENU


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """وقتی ادمین روی پیام فوروارد‌شده‌ی یه کاربر Reply می‌زنه، جوابش رو مستقیم
    برای همون کاربر می‌فرستیم. اگه پیام مربوط به این قابلیت نبود، کاری نمی‌کنیم
    و می‌ذاریم بقیه‌ی handler ها طبق روال عادی پیام رو پردازش کنن."""
    if not ADMIN_ID or not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    if not update.message or not update.message.reply_to_message:
        return

    mapping = load_contact_map()
    target_user_id = mapping.get(str(update.message.reply_to_message.message_id))
    if target_user_id is None:
        return  # این یه ریپلای معمولیه، نه جواب به کاربر — کاری نمی‌کنیم

    reply_text = update.message.text or ""
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"📩 پاسخ پشتیبانی:\n\n{reply_text}",
        )
        await update.message.reply_text("✅ جوابت برای کاربر ارسال شد.")
    except Exception as e:
        logger.warning("Could not deliver admin reply to user: %s", e)
        await update.message.reply_text(
            "⚠️ نشد جواب رو بفرستم (شاید کاربر ربات رو بلاک کرده)."
        )

    # این پیام کاملاً پردازش شد؛ نذار وارد فلوی عادی مکالمه هم بشه.
    raise ApplicationHandlerStop


# ---------------------------------------------------------------------------
# Broadcast — فقط برای ادمین
# ---------------------------------------------------------------------------
async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update)
    await update.message.reply_text(f"شناسه‌ی عددی تو تلگرام: {update.effective_user.id}")


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        return  # کاربر عادی، سکوت می‌کنیم

    match = re.match(r"^/broadcast(?:@\S+)?\s+([\s\S]+)$", update.message.text or "", re.DOTALL)
    if not match:
        await update.message.reply_text(
            "استفاده: /broadcast متن پیامی که می‌خوای برای همه بفرستی"
        )
        return

    text = match.group(1).strip()
    users = load_users()
    if not users:
        await update.message.reply_text("هنوز هیچ کاربری ثبت نشده.")
        return

    sent, failed = 0, 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"✅ ارسال شد به {sent} کاربر" + (f" (ناموفق: {failed})" if failed else "")
    )


# ---------------------------------------------------------------------------
# لغو / خطا
# ---------------------------------------------------------------------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "لغو شد. هر وقت خواستی دوباره /start رو بزن.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("برای شروع، دستور /start رو بفرست.")


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "متغیر محیطی BOT_TOKEN تنظیم نشده. توکن ربات رو از BotFather بگیر و در "
            "Environment Variables تنظیم کن."
        )

    application = Application.builder().token(token).build()

    # این باید قبل از ConversationHandler چک بشه تا اگه ادمین داشت به یه پیام
    # کاربر Reply می‌زد، مستقیم پردازش بشه و وارد فلوی منو نشه.
    application.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY, handle_admin_reply), group=-1
    )

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu_choice)],
            SAWABEGH_Q: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sawabegh)],
            KONKUR_Q: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_konkur)],
            CONTACT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_contact)],
            REGION_Q: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_region)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv)
    application.add_handler(CommandHandler("myid", myid_cmd))
    application.add_handler(CommandHandler("broadcast", broadcast_cmd))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("Bot starting (polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

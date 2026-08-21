# -*- coding: utf-8 -*-
"""
ربات تلگرامی «تخمین تراز سوابق تحصیلی و کنکور ۱۴۰۴ - رشته تجربی»

منطق این ربات دقیقاً بر اساس فرمول‌های اکسل taraz_estimator است:
- جست‌وجوی خطی (lookup + interpolation) در جدول‌های واقعی کارنامه‌ها
- میانگین وزنی با ضرایب رسمی
- ترکیب نهایی سوابق/کنکور طبق سهم ۶۰٪ / ۴۰٪ اعلامی سال ۱۴۰۴

ورودی هر بخش یک‌جا گرفته می‌شه (شبیه پر کردن ستون توی اکسل): دانش‌آموز همه‌ی
نمره‌ها/درصدها رو با فاصله یا کاما، پشت سر هم، توی یک پیام می‌فرسته.
"""

import json
import logging
import os
import re
from pathlib import Path

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
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

SAWABEGH_RECORDS_SHARE = 0.60  # سهم رسمی سوابق تحصیلی در ۱۴۰۴
KONKUR_SPECIALIZED_SHARE = 0.40  # سهم دروس تخصصی کنکور

# فارسی/عربی -> ارقام لاتین، برای اینکه هرجور کاربر عدد را تایپ کند بخوانیم
DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
)

SKIP_TOKENS = {"-", "_", "x", "X", "ندادم", "رد", "خالی", "skip", "none", ""}

# ---------------------------------------------------------------------------
# حالت‌های مکالمه
# ---------------------------------------------------------------------------
MAIN_MENU, SAWABEGH_INPUT, KONKUR_INPUT = range(3)

MENU_SAWABEGH = "📚 تراز سوابق تحصیلی"
MENU_KONKUR = "📝 تراز کنکور (اختصاصی)"
MENU_BOTH = "🎯 هردو + تراز نهایی"
MENU_CANCEL = "لغو"


def parse_number(token: str):
    """عدد فارسی/انگلیسی را به float تبدیل می‌کند، یا None برمی‌گرداند."""
    cleaned = token.strip().translate(DIGIT_MAP)
    cleaned = cleaned.replace(",", ".").replace("٫", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def split_tokens(text: str):
    """پیام کاربر رو با فاصله/کاما/خط جدید/اسلش می‌شکنه به لیست توکن‌ها."""
    tokens = re.split(r"[\s,،/;]+", text.strip())
    return [t for t in tokens if t != ""]


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


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[MENU_SAWABEGH], [MENU_KONKUR], [MENU_BOTH], [MENU_CANCEL]],
        resize_keyboard=True,
    )


def cancel_keyboard():
    return ReplyKeyboardMarkup([[MENU_CANCEL]], resize_keyboard=True)


# ---------------------------------------------------------------------------
# شروع / منو
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "سلام 👋\n"
        "این ربات تراز تخمینی سوابق تحصیلی و کنکور ۱۴۰۴ (رشته تجربی) رو بر اساس "
        "جدول واقعی کارنامه‌های ۱۴۰۴ حساب می‌کنه.\n\n"
        "یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=main_menu_keyboard(),
    )
    return MAIN_MENU


async def menu_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == MENU_SAWABEGH:
        return await prompt_sawabegh(update, context, then_konkur=False)
    if text == MENU_KONKUR:
        return await prompt_konkur(update, context, combine=False)
    if text == MENU_BOTH:
        return await prompt_sawabegh(update, context, then_konkur=True)
    if text == MENU_CANCEL:
        return await cancel(update, context)
    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های روی صفحه‌کلید رو انتخاب کن.",
        reply_markup=main_menu_keyboard(),
    )
    return MAIN_MENU


# ---------------------------------------------------------------------------
# مسیر سوابق تحصیلی — یک‌جا برای همه‌ی ۱۰ درس
# ---------------------------------------------------------------------------
async def prompt_sawabegh(update: Update, context: ContextTypes.DEFAULT_TYPE, then_konkur: bool) -> int:
    context.user_data["then_konkur"] = then_konkur
    lines = ["نمره‌های نهایی (بین ۱۲ تا ۲۰) رو به همین ترتیب، با فاصله یا کاما، توی یک پیام بفرست:\n"]
    for i, (name, coeff, _col) in enumerate(SAWABEGH_SUBJECTS, start=1):
        lines.append(f"{i}. {name} (ضریب {coeff})")
    lines.append("\nمثال:\n17 15 18.5 16 20 19 17.5 14 15 16")
    await update.message.reply_text("\n".join(lines), reply_markup=cancel_keyboard())
    return SAWABEGH_INPUT


async def handle_sawabegh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == MENU_CANCEL:
        return await cancel(update, context)

    tokens = split_tokens(text)
    n = len(SAWABEGH_SUBJECTS)
    if len(tokens) != n:
        await update.message.reply_text(
            f"باید دقیقاً {n} عدد بفرستی (یکی به ازای هر درس)، ولی {len(tokens)} تا گرفتم.\n"
            "دوباره امتحان کن، همه رو توی یک پیام و به همون ترتیب لیست بفرست."
        )
        return SAWABEGH_INPUT

    scores = {}
    errors = []
    for i, tok in enumerate(tokens):
        val = parse_number(tok)
        name = SAWABEGH_SUBJECTS[i][0]
        if val is None:
            errors.append(f"«{tok}» برای «{name}» عدد معتبر نیست")
            continue
        if val < 0 or val > 20:
            errors.append(f"نمره‌ی «{name}» ({tok}) باید بین ۰ تا ۲۰ باشه")
            continue
        scores[i] = val

    if errors:
        await update.message.reply_text(
            "⚠️ این مشکل‌ها رو داشتیم:\n" + "\n".join(f"• {e}" for e in errors) +
            "\n\nدوباره همه‌ی نمرات رو با ترتیب درست بفرست."
        )
        return SAWABEGH_INPUT

    low_grade_names = [SAWABEGH_SUBJECTS[i][0] for i, v in scores.items() if v < 12]

    result = compute_sawabegh(scores)
    context.user_data["saw_result"] = result

    lines = ["✅ نتیجه‌ی تراز سوابق تحصیلی:\n"]
    for i, (name, coeff, _col) in enumerate(SAWABEGH_SUBJECTS):
        lines.append(f"• {name}: {result['per_subject'][i]:.0f}")
    lines.append(f"\n🎯 تراز تخمینی سوابق تحصیلی: {result['final']:.0f}")
    if low_grade_names:
        lines.append(
            "\n⚠️ توجه: جدول منبع فقط نمرات ۱۲ تا ۲۰ رو پوشش می‌ده؛ برای "
            + "، ".join(low_grade_names)
            + " دقت مدل کمتره."
        )
    await update.message.reply_text("\n".join(lines))

    if context.user_data.get("then_konkur"):
        return await prompt_konkur(update, context, combine=True)

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
# مسیر کنکور — یک‌جا برای همه‌ی درس‌های تخصصی
# ---------------------------------------------------------------------------
async def prompt_konkur(update: Update, context: ContextTypes.DEFAULT_TYPE, combine: bool) -> int:
    context.user_data["combine"] = combine
    lines = ["درصدهای تراز (بین ۵- تا ۱۰۰) رو به همین ترتیب، با فاصله یا کاما، توی یک پیام بفرست:\n"]
    for i, (name, coeff, _col, required) in enumerate(KONKUR_SUBJECTS, start=1):
        tag = "" if required else " — اختیاری، اگه امتحان ندادی به‌جاش - بذار"
        lines.append(f"{i}. {name} (ضریب {coeff}){tag}")
    lines.append("\nمثال:\n25 33 44 32 10\nیا اگه زمین‌شناسی نداشتی:\n25 33 44 32 -")
    await update.message.reply_text("\n".join(lines), reply_markup=cancel_keyboard())
    return KONKUR_INPUT


async def handle_konkur(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == MENU_CANCEL:
        return await cancel(update, context)

    tokens = split_tokens(text)
    n = len(KONKUR_SUBJECTS)
    if len(tokens) != n:
        await update.message.reply_text(
            f"باید دقیقاً {n} مقدار بفرستی (یکی به ازای هر درس)، ولی {len(tokens)} تا گرفتم.\n"
            "دوباره امتحان کن، همه رو توی یک پیام و به همون ترتیب لیست بفرست."
        )
        return KONKUR_INPUT

    scores = {}
    errors = []
    for i, tok in enumerate(tokens):
        name, coeff, col, required = KONKUR_SUBJECTS[i]
        if tok in SKIP_TOKENS:
            if required:
                errors.append(f"«{name}» اجباریه، نمی‌تونی ردش کنی")
            else:
                scores[i] = None
            continue
        val = parse_number(tok)
        if val is None:
            errors.append(f"«{tok}» برای «{name}» عدد معتبر نیست")
            continue
        if val < -5 or val > 100:
            errors.append(f"درصد «{name}» ({tok}) باید بین ۵- تا ۱۰۰ باشه")
            continue
        scores[i] = val

    if errors:
        await update.message.reply_text(
            "⚠️ این مشکل‌ها رو داشتیم:\n" + "\n".join(f"• {e}" for e in errors) +
            "\n\nدوباره همه‌ی مقدارها رو با ترتیب درست بفرست."
        )
        return KONKUR_INPUT

    result = compute_konkur(scores)
    context.user_data["kon_result"] = result

    lines = ["✅ نتیجه‌ی تراز کنکور (فقط دروس اختصاصی):\n"]
    for i, (name, coeff, _col, _req) in enumerate(KONKUR_SUBJECTS):
        val = result["per_subject"][i]
        lines.append(f"• {name}: {'—' if val is None else f'{val:.0f}'}")
    lines.append(f"\n🎯 تراز تخمینی کنکور (اختصاصی): {result['final']:.0f}")
    await update.message.reply_text("\n".join(lines))

    if context.user_data.get("combine") and "saw_result" in context.user_data:
        await send_final_combination(update, context)

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
    saw_final = context.user_data["saw_result"]["final"]
    kon_final = context.user_data["kon_result"]["final"]
    combined = round(
        SAWABEGH_RECORDS_SHARE * saw_final + KONKUR_SPECIALIZED_SHARE * kon_final
    )
    await update.message.reply_text(
        "———————————\n"
        f"📚 تراز سوابق: {saw_final:.0f}\n"
        f"📝 تراز کنکور (اختصاصی): {kon_final:.0f}\n"
        f"⚖️ ترکیب با سهم رسمی ۱۴۰۴ (سوابق ۶۰٪ / اختصاصی ۴۰٪):\n"
        f"🏁 تراز نهایی تخمینی: {combined}\n\n"
        "⚠️ این عدد فقط یه تخمینه؛ سهم دروس عمومی کنکور در این محاسبه لحاظ نشده "
        "چون طبق تغییرات ۱۴۰۴ حذف شدن."
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

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu_choice)],
            SAWABEGH_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sawabegh)],
            KONKUR_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_konkur)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv)
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("Bot starting (polling)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

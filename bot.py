import os
import json
import re
import anthropic
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
AV_SHEET_ID = "1f-1lkgr7nGiQofoREnhfbszjaJFu17OtZaMJ09_sLWw"
SECRET_PASSWORD = os.environ.get("SECRET_PASSWORD", "Adel2026")

PROJECTS = ["D11 BUSINESS", "D12 Medical", "METRO +", "TIJAN", "WW1", "WW2", "STAGE X", "RESALE", "MIDST"]

PROJECT_ALIASES = {
    "d11": "D11 BUSINESS",
    "d12": "D12 Medical",
    "ww1": "WW1",
    "ww2": "WW2",
    "tijan": "TIJAN",
    "midst": "MIDST",
    "stage x": "STAGE X",
    "resale": "RESALE",
    "metro": "METRO +",
}

SYSTEM_PROMPT = (
    "أنت مساعد داخلي لفريق مبيعات معمار دجلة. "
    "مصدر الحقيقة الوحيد هو بيانات الشيت. "
    "ممنوع اختراع أي أسعار أو وحدات أو مساحات أو شروط دفع أو بيانات عملاء. "
    "ردودك قصيرة وطبيعية بالمصري. "
    "لا تكتب سكريبتات إلا لو المستخدم طلب سكريبت. "
    "لا تكتب إعلانات إلا لو المستخدم طلب إعلان."
)

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)
av_sh = gc.open_by_key(AV_SHEET_ID)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

user_context = {}
chat_history = {}
current_unit = {}
headers_cache = {}

NO_CONFIRMED_DATA = "مش لاقي بيانات مؤكدة في الشيت للطلب ده. ابعتلي كود الوحدة أو الميزانية بصيغة أوضح."

BUDGET_WORDS = [
    "مقدم", "مقدمة", "مقدمه", "مقدمته",
    "ميزانية", "إجمالي", "اجمالي",
    "رينج", "range", "total", "budget", "down"
]

DATA_WORDS = BUDGET_WORDS + [
    "وحدة", "الوحدة", "كود", "مشروع", "المشروع",
    "اتاحة", "إتاحة", "اتاحه",
    "available", "availability",
    "سعر", "price", "area", "مساحة",
    "payment plan", "بلان", "خطة سداد",
    "قسط", "اقساط", "أقساط",
    "تسليم", "delivery"
]

CHEAP_WORDS = ["الأرخص", "ارخص", "أرخص", "اقل سعر", "أقل سعر", "cheapest"]


def normalize_digits(text):
    return str(text).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,"))


def clean(s):
    try:
        return float(re.sub(r"[^\d.]", "", normalize_digits(str(s))))
    except:
        return 0


def amount_value(num, unit=None, kind=None):
    try:
        v = float(normalize_digits(str(num)).replace(",", "."))
    except:
        return 0

    unit = (unit or "").lower().strip()

    if unit in ["مليون", "ملايين", "million", "m"]:
        return v * 1_000_000

    if unit in ["ألف", "الف", "thousand", "k"]:
        return v * 1_000

    # لو المستخدم كتب مقدم 600 غالبًا يقصد 600 ألف
    if kind == "down" and v < 10000:
        return v * 1000

    # لو المستخدم كتب إجمالي 3 أو 3.5 غالبًا يقصد مليون
    if kind == "total" and v < 100:
        return v * 1_000_000

    return v


def parse_budget(text):
    t = normalize_digits(text).lower()
    t = t.replace("|", " ").replace("،", " ").replace("ـ", "-")

    amount = r"(\d+(?:[\.,]\d+)?)\s*(مليون|ملايين|ألف|الف|million|thousand|m|k)?"

    down_min = down_max = None
    total_min = total_max = None

    # مقدم بعد الكلمة
    m = re.search(r"(?:مقدم|مقدمة|مقدمه|مقدمته|down)[^\d]{0,20}" + amount, t)
    if m:
        d = amount_value(m.group(1), m.group(2), "down")
        down_min = down_max = d

    # رقم قبل كلمة مقدم
    if down_min is None:
        m = re.search(amount + r"[^\d]{0,20}(?:مقدم|مقدمة|مقدمه|مقدمته|down)", t)
        if m:
            d = amount_value(m.group(1), m.group(2), "down")
            down_min = down_max = d

    # إجمالي من X ل Y
    m = re.search(
        r"(?:إجمالي|اجمالي|total|budget|رينج)?[^\d]{0,30}"
        r"من\s*" + amount + r"\s*(?:ل|الى|إلى|-|to)\s*" + amount,
        t
    )
    if m:
        u1 = m.group(2) or m.group(4)
        u2 = m.group(4) or m.group(2)
        total_min = amount_value(m.group(1), u1, "total")
        total_max = amount_value(m.group(3), u2, "total")

    # إجمالي 3-3.5 مليون
    if total_min is None:
        m = re.search(
            r"(?:إجمالي|اجمالي|total|budget|رينج)?[^\d]{0,30}"
            + amount + r"\s*-\s*" + amount,
            t
        )
        if m:
            u1 = m.group(2) or m.group(4)
            u2 = m.group(4) or m.group(2)
            total_min = amount_value(m.group(1), u1, "total")
            total_max = amount_value(m.group(3), u2, "total")

    # إجمالي رقم واحد
    if total_min is None:
        m = re.search(r"(?:إجمالي|اجمالي|total|budget|رينج)[^\d]{0,25}" + amount, t)
        if m:
            total_min = total_max = amount_value(m.group(1), m.group(2), "total")

    # لو فيه مقدم وإجمالي مش واضح، خُد آخر رقمين كإجمالي
    if total_min is None:
        nums = re.findall(amount, t)
        if len(nums) >= 2:
            vals = []
            for n, u in nums:
                vals.append(amount_value(n, u, "total"))

            # لو آخر رقم فيه مليون واللي قبله من غير وحدة
            if nums[-1][1] and not nums[-2][1]:
                vals[-2] = amount_value(nums[-2][0], nums[-1][1], "total")

            total_min, total_max = vals[-2], vals[-1]

    # لو الرسالة فيها مقدم فقط
    if total_min is None and down_min is not None:
        total_min, total_max = 0, 10**12

    if total_min is not None and total_max is not None and total_min > total_max:
        total_min, total_max = total_max, total_min

    if total_min is not None and total_max is not None:
        return {
            "total_min": total_min,
            "total_max": total_max,
            "down_min": down_min,
            "down_max": down_max
        }

    return None


def is_budget_request(text):
    ml = normalize_digits(text).lower()
    has_budget_word = any(k.lower() in ml for k in BUDGET_WORDS)
    has_number = any(c.isdigit() for c in ml)
    has_amount_unit = re.search(r"\d+(?:[\.,]\d+)?\s*(مليون|ملايين|ألف|الف|million|thousand|m|k)", ml) is not None
    return (has_budget_word and has_number) or has_amount_unit


def is_amount_only(text):
    ml = normalize_digits(text).strip().lower()
    return re.fullmatch(r"\d+(?:[\.,]\d+)?\s*(مليون|ملايين|ألف|الف|million|thousand|m|k)?", ml) is not None


def is_data_request(text):
    ml = text.lower()
    return any(k.lower() in ml for k in DATA_WORDS) or detect_project(text) is not None


def ensure_context(uid):
    if uid not in user_context:
        user_context[uid] = {}
    return user_context[uid]


def remember_project(uid, project):
    if project:
        ensure_context(uid)["last_project"] = project


def remember_unit(uid, unit):
    if unit:
        current_unit[uid] = unit
        ctx = ensure_context(uid)
        ctx["last_unit"] = unit
        ctx["last_project"] = unit.get("sheet")


def remember_results(uid, results, is_close=False, budget=None):
    ctx = ensure_context(uid)
    ctx["results"] = results
    ctx["last_results"] = results
    ctx["is_close"] = is_close
    if budget:
        ctx["budget"] = budget
    if results:
        remember_unit(uid, min(results, key=lambda x: x.get("total_num") or 0))


def clear_pending(uid):
    ctx = ensure_context(uid)
    ctx.pop("pending_intent", None)
    ctx.pop("last_requested_field", None)
    ctx.pop("clarification_attempts", None)


def has_confirmed_context(uid):
    ctx = user_context.get(uid, {})
    return bool(current_unit.get(uid) or ctx.get("results") or ctx.get("last_results"))


def detect_project(text):
    t = text.lower()
    for a, r in PROJECT_ALIASES.items():
        if a in t:
            return r
    for p in PROJECTS:
        if p.lower() in t:
            return p
    return None


def parse_pu(text):
    if "-" in text:
        a, b = text.split("-", 1)
        p = detect_project(a.strip())
        if p and b.strip():
            return p, b.strip().upper()
    return None, None


def get_headers(ws):
    if ws.title in headers_cache:
        return headers_cache[ws.title]

    h = {}
    for row in (ws.get_all_values() or [])[:3]:
        for i, c in enumerate(row):
            k = c.strip().lower().replace("_", "")
            kc = k.replace(" ", "")

            if kc in ["code", "u."]:
                h["code"] = i
            elif kc == "area":
                h["area"] = i
            elif kc in ["price", "pricepermeter"]:
                h["price"] = i
            elif kc == "status":
                h["status"] = i
            elif "totalpriceafterdi" in kc:
                h["total_after"] = i
            elif kc in ["totalprice", "total"]:
                if "total_after" not in h:
                    h["total"] = i
            elif "down" in kc and ("pay" in kc or kc == "down"):
                h["down"] = i
            elif kc in ["instalments", "installments", "batchafteryear", "insta"]:
                h["inst"] = i
            elif kc in ["cashdiscount", "discount"]:
                h["disc"] = i
            elif "delivery" in kc:
                h["delivery"] = i

    headers_cache[ws.title] = h
    return h


def gcell(row, h, k, d=""):
    i = h.get(k)
    return row[i].strip() if i is not None and i < len(row) else d


def get_status(row, h):
    i = h.get("status")
    if i is not None and i < len(row):
        v = row[i].strip().lower()
        if v in ["available", "reserved", "hold"]:
            return v

    for c in row:
        if c.strip().lower() in ["available", "reserved", "hold"]:
            return c.strip().lower()

    return ""


def row_to_unit(row, ws_title, h):
    bad = ["available", "reserved", "hold", ""]
    total = gcell(row, h, "total_after") or gcell(row, h, "total")
    down = gcell(row, h, "down")

    return {
        "sheet": ws_title,
        "code": gcell(row, h, "code"),
        "area": gcell(row, h, "area"),
        "price": gcell(row, h, "price") if gcell(row, h, "price") not in bad else "",
        "total": total,
        "total_num": clean(total),
        "down": down if down not in bad else "",
        "down_num": clean(down),
        "inst": gcell(row, h, "inst") if gcell(row, h, "inst") not in bad else "",
        "delivery": gcell(row, h, "delivery") if gcell(row, h, "delivery") not in bad else "",
        "status": get_status(row, h)
    }


def find_unit(code, project=None):
    code = code.strip().upper().replace(" ", "")
    for ws in av_sh.worksheets():
        if project and project.lower() not in ws.title.lower():
            continue
        h = get_headers(ws)
        ci = h.get("code", 0)
        for row in (ws.get_all_values() or [])[1:]:
            if row and row[ci].strip().upper().replace(" ", "") == code:
                return row_to_unit(row, ws.title, h)
    return None


def search_budget(tmin, tmax, dmin=None, dmax=None, project=None):
    exact, close = [], []

    for ws in av_sh.worksheets():
        if project and project.lower() not in ws.title.lower():
            continue

        h = get_headers(ws)
        ci = h.get("code", 0)

        for row in (ws.get_all_values() or [])[1:]:
            if not row or not row[ci].strip():
                continue
            if get_status(row, h) != "available":
                continue

            u = row_to_unit(row, ws.title, h)
            t, d = u["total_num"], u["down_num"]

            if t == 0:
                continue

            ok_t = tmin <= t <= tmax
            ok_d = (dmin is None or dmax is None) or (d != 0 and dmin <= d <= dmax)

            close_t = tmin * 0.8 <= t <= tmax * 1.2
            close_d = True
            if dmin is not None and dmax is not None:
                close_d = d != 0 and dmin * 0.8 <= d <= dmax * 1.2

            if ok_t and ok_d:
                exact.append(u)
            elif close_t and close_d:
                close.append(u)

    return exact, close


def run_budget_search(uid, data, project=None):
    tmin, tmax = data.get("total_min"), data.get("total_max")
    if tmin is None or tmax is None:
        return NO_CONFIRMED_DATA

    exact, close = search_budget(tmin, tmax, data.get("down_min"), data.get("down_max"), project)

    remember_project(uid, project)
    remember_results(uid, exact or close, len(exact) == 0, {"tmin": tmin, "tmax": tmax})

    if exact:
        parts = [fmt_unit(u) for u in exact[:5]]
        return f"لقيت لك {len(exact)} وحدات مناسبة:\n\n" + "\n\n---\n\n".join(parts)

    if close:
        parts = [fmt_unit(u) for u in close[:5]]
        return "مفيش مطابق بالظبط، بس دي أقرب بدائل في حدود 20%:\n\n" + "\n\n---\n\n".join(parts)

    return NO_CONFIRMED_DATA


def project_stats(pfilter=None):
    res = {}
    for ws in av_sh.worksheets():
        if pfilter and pfilter.lower() not in ws.title.lower():
            continue
        h = get_headers(ws)
        ci = h.get("code", 0)
        cnt = {"available": 0, "reserved": 0, "hold": 0}

        for row in (ws.get_all_values() or [])[1:]:
            if row and row[ci].strip():
                s = get_status(row, h)
                if s in cnt:
                    cnt[s] += 1

        if sum(cnt.values()) > 0:
            res[ws.title] = cnt

    return res


def save_sale(project, unit, price, client_name):
    try:
        try:
            ws = sh.worksheet("المبيعات")
        except:
            ws = sh.add_worksheet("المبيعات", 1000, 10)
            ws.append_row(["المشروع", "الوحدة", "السعر", "العميل", "التاريخ"])

        from datetime import datetime
        ws.append_row([project, unit, price, client_name, datetime.now().strftime("%Y-%m-%d %H:%M")])
    except:
        pass


def get_sales():
    try:
        ws = sh.worksheet("المبيعات")
        data = ws.get_all_values()
        if len(data) <= 1:
            return "لا توجد مبيعات."
        return "\n".join([f"• {r[0]}-{r[1]}-{r[2]}-{r[3]}-{r[4]}" for r in data[1:] if len(r) >= 4])
    except:
        return "لا توجد مبيعات."


def fmt_unit(u):
    e = "✅" if u["status"] == "available" else "🔴" if u["status"] == "reserved" else "🔵"

    t = f"*{u['code']}* - {u['sheet']}\n"
    if u.get("area"):
        t += f"📐 {u['area']}م²\n"
    if u.get("price"):
        t += f"💰 سعر المتر: {u['price']} جنيه\n"
    if u.get("total"):
        t += f"💵 الإجمالي: {u['total']} جنيه\n"
    if u.get("down"):
        t += f"🔑 المقدم: {u['down']}\n"
    if u.get("delivery"):
        t += f"🏗️ التسليم: {u['delivery']}\n"
    if u.get("inst"):
        t += f"📅 الأقساط: {u['inst']}\n"
    t += f"{e} {u['status']}"

    return t


def fmt_stats(res):
    if not res:
        return NO_CONFIRMED_DATA
    return "".join([f"📊 *{p}*\n✅{c['available']} 🔴{c['reserved']} 🔵{c['hold']} 📦{sum(c.values())}\n\n" for p, c in res.items()])


def fmt_plan(u, plan):
    return (
        f"💳 *Payment Plan - {u['code']}*\n"
        f"🏢 {u['sheet']} | 📐 {u.get('area', '')}م²\n\n"
        f"💵 السعر: {plan['total']:,.0f} جنيه\n"
        f"🔑 المقدم {plan['dp']}%: {plan['down']:,.0f} جنيه\n"
        f"📊 المتبقي: {plan['rem']:,.0f} جنيه\n\n"
        f"على {plan['years']} سنين:\n"
        f"• ربع سنوي: {plan['q']:,.0f} جنيه\n"
        f"• شهري: {plan['m']:,.0f} جنيه"
    )


def calc_plan(total_str, dp, years):
    try:
        t = clean(total_str)
        d = t * (dp / 100)
        r = t - d
        return {"total": t, "down": d, "rem": r, "q": r / (years * 4), "m": r / (years * 12), "years": years, "dp": dp}
    except:
        return None


def sales_menu():
    return ReplyKeyboardMarkup([
        ["تفاصيل وحدة", "بحث بالميزانية"],
        ["Payment Plan", "سكريبت واتساب"],
        ["كتابة إعلان", "إحصائيات المشاريع"],
        ["تسجيل بيعة"]
    ], resize_keyboard=True)


MENU_INSTRUCTIONS = {
    "تفاصيل وحدة": "ابعت اسم المشروع وكود الوحدة بالشكل ده:\nWW1 - W1 C3",
    "بحث بالميزانية": "مثال:\nمقدم 600 الف اجمالي من 3 ل 4 مليون",
    "Payment Plan": "مثال:\npayment plan WW1 - W1 C3 مقدم 20% على 5 سنين",
    "سكريبت واتساب": "ابعت الوحدة مع كلمة سكريبت، مثال:\nسكريبت WW1 - W1 C3",
    "كتابة إعلان": "ابعت الوحدة الأول، وبعدها اكتب: اعلان",
    "إحصائيات المشاريع": "اكتب اسم المشروع أو اطلب كل الإحصائيات.",
    "تسجيل بيعة": "مثال:\nبعنا WW1 - W1 C3 بسعر 2500000 للعميل أحمد"
}


def style_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Pain Point", callback_data="s_pain"),
         InlineKeyboardButton("المقارنة", callback_data="s_compare")],
        [InlineKeyboardButton("FOMO", callback_data="s_fomo"),
         InlineKeyboardButton("ROI", callback_data="s_roi")],
        [InlineKeyboardButton("القصة", callback_data="s_story"),
         InlineKeyboardButton("Social Proof", callback_data="s_social")],
        [InlineKeyboardButton("Exclusivity", callback_data="s_exclusive")]
    ])


STYLES = {
    "s_pain": ("Pain Point", "Start with client problem"),
    "s_compare": ("المقارنة", "Compare rent vs buy"),
    "s_fomo": ("FOMO", "Time pressure and scarcity"),
    "s_roi": ("ROI", "Calculate the return"),
    "s_story": ("القصة", "Success story"),
    "s_social": ("Social Proof", "Numbers and testimonials"),
    "s_exclusive": ("Exclusivity", "Exclusivity and scarcity"),
}


def add_h(uid, role, content):
    if uid not in chat_history:
        chat_history[uid] = []
    chat_history[uid].append({"role": role, "content": content})
    if len(chat_history[uid]) > 20:
        chat_history[uid] = chat_history[uid][-20:]


def get_h(uid):
    return chat_history.get(uid, [])


def ai(messages, system=None, max_tokens=400):
    return client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system or SYSTEM_PROMPT,
        messages=messages
    ).content[0].text.strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    chat_history[uid] = []
    current_unit.pop(uid, None)
    user_context.pop(uid, None)

    await update.message.reply_text(
        "أهلاً، ابعتلي اللي محتاجه وأنا هساعدك.",
        reply_markup=sales_menu()
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    sk = q.data

    if sk not in STYLES:
        return

    sname, sinst = STYLES[sk]
    u = current_unit.get(uid)

    if not u:
        await q.edit_message_text(NO_CONFIRMED_DATA)
        return

    unit_data = fmt_unit(u)
    reply = ai(
        [{"role": "user", "content": "write script " + sname}],
        system=SYSTEM_PROMPT + " unit data: " + unit_data + " style: " + sname + " - " + sinst + " write a short whatsapp script in egyptian arabic based on confirmed unit data only.",
        max_tokens=800
    )

    await q.edit_message_text("*script " + sname + "*\n\n" + reply, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    uid = update.message.from_user.id
    ml = msg.lower()
    ctx = ensure_context(uid)

    if msg in MENU_INSTRUCTIONS:
        await update.message.reply_text(MENU_INSTRUCTIONS[msg], reply_markup=sales_menu())
        return

    # pending budget clarification
    if ctx.get("pending_intent") == "budget_search":
        if is_amount_only(msg) or is_budget_request(msg):
            if is_amount_only(msg) and ctx.get("last_requested_field") == "down_payment":
                m = re.search(
                    r"(\d+(?:[\.,]\d+)?)\s*(مليون|ملايين|ألف|الف|million|thousand|m|k)?",
                    normalize_digits(msg).lower()
                )
                if m:
                    d = amount_value(m.group(1), m.group(2), "down")
                    data = {
                        "down_min": d,
                        "down_max": d,
                        "total_min": 0,
                        "total_max": 10**12
                    }
                else:
                    data = None
            else:
                data = parse_budget(msg)

            clear_pending(uid)

            if data:
                out = run_budget_search(uid, data, ctx.get("last_project"))
                await update.message.reply_text(out, parse_mode="Markdown")
                return

        attempts = ctx.get("clarification_attempts", 0) + 1
        ctx["clarification_attempts"] = attempts

        if attempts >= 2:
            clear_pending(uid)
            await update.message.reply_text("مش فاهم المطلوب بشكل واضح.")
        else:
            await update.message.reply_text("اكتبلي الرقم بالمقدم أو الإجمالي بشكل أوضح.")
        return

    if user_context.get(uid, {}).get("waiting_password"):
        if msg == SECRET_PASSWORD:
            user_context[uid] = {"authenticated": True}
            await update.message.reply_text("سجل المبيعات:\n\n" + get_sales())
        else:
            await update.message.reply_text("كلمة المرور غير صحيحة.")
        return

    if "مبيعات" in ml or "بايعين" in ml:
        if user_context.get(uid, {}).get("authenticated"):
            await update.message.reply_text("سجل المبيعات:\n\n" + get_sales())
        else:
            user_context[uid] = {"waiting_password": True}
            await update.message.reply_text("ابعت كلمة المرور:")
        return

    if "بيعة" in ml or "بعنا" in ml or "اتباع" in ml:
        try:
            t = ai(
                [{"role": "user", "content": msg}],
                system='JSON only: {"action":"sale","project":"","unit":"","price":"","client":""}',
                max_tokens=200
            )
            d = json.loads(t[t.find("{"):t.rfind("}") + 1])
            if d.get("action") == "sale":
                save_sale(d["project"], d["unit"], d["price"], d["client"])
                current_unit.pop(uid, None)
                await update.message.reply_text("✅ " + d["project"] + " | " + d["unit"] + " | " + d["price"] + " | " + d["client"])
            return
        except:
            pass

    if ml.strip() in ["تمام", "ok", "okay", "تم", "موافق", "next"]:
        current_unit.pop(uid, None)
        user_context.pop(uid, None)
        await update.message.reply_text("تمام! في وحدة أو عميل تاني؟")
        return

    if "سكريبت" in ml or "script" in ml:
        p, uc = parse_pu(msg)
        if p and uc:
            u = find_unit(uc, p)
            if u:
                remember_unit(uid, u)

        u = current_unit.get(uid)

        if u:
            await update.message.reply_text("اختر الأسلوب:", reply_markup=style_buttons())
        else:
            await update.message.reply_text(NO_CONFIRMED_DATA)
        return

    if "اعلان" in ml or "إعلان" in ml:
        u = current_unit.get(uid)
        if not u:
            await update.message.reply_text(NO_CONFIRMED_DATA)
            return

        unit_data = fmt_unit(u)
        reply = ai(
            [{"role": "user", "content": msg}],
            system=SYSTEM_PROMPT + " unit: " + unit_data + " write 3 short ad variants in egyptian arabic based on this confirmed unit data only.",
            max_tokens=1000
        )
        await update.message.reply_text(reply)
        return

    if "payment plan" in ml or "بلان" in ml or "خطة سداد" in ml:
        p, uc = parse_pu(msg)
        u = find_unit(uc, p) if p and uc else current_unit.get(uid)

        if u:
            remember_unit(uid, u)
            dp_m = re.search(r"(\d+)\s*%", msg)
            yr_m = re.search(r"(\d+)\s*سن", msg)

            plan = calc_plan(
                u["total"],
                int(dp_m.group(1)) if dp_m else 20,
                int(yr_m.group(1)) if yr_m else 5
            )

            if plan:
                add_h(uid, "user", msg)
                add_h(uid, "assistant", "Payment Plan " + u["code"])
                await update.message.reply_text(fmt_plan(u, plan), parse_mode="Markdown")
                return

        await update.message.reply_text(NO_CONFIRMED_DATA)
        return

    p, uc = parse_pu(msg)
    if p and uc:
        u = find_unit(uc, p)
        if u:
            remember_unit(uid, u)
            add_h(uid, "user", msg)
            add_h(uid, "assistant", "تفاصيل " + u["code"])
            await update.message.reply_text(fmt_unit(u), parse_mode="Markdown")
        else:
            await update.message.reply_text(NO_CONFIRMED_DATA)
        return

    if is_budget_request(msg):
        d = parse_budget(msg)

        if not d:
            ctx["pending_intent"] = "budget_search"
            ctx["last_requested_field"] = "down_payment"
            ctx["clarification_attempts"] = 1
            await update.message.reply_text("تقصد مقدم كام تقريبًا؟")
            return

        dp = detect_project(msg) or ctx.get("last_project")
        out = run_budget_search(uid, d, dp)
        add_h(uid, "user", msg)
        await update.message.reply_text(out, parse_mode="Markdown")
        return

    dp = detect_project(msg)

    if any(k in ml for k in ["كام وحدة", "كل المشاريع", "جميع", "إتاحة", "اتاحه", "احصائيه"]):
        stats = project_stats(dp)
        await update.message.reply_text(fmt_stats(stats), parse_mode="Markdown")
        return

    if any(k in ml for k in CHEAP_WORDS):
        results = ctx.get("results") or ctx.get("last_results") or []
        if results:
            cheapest = sorted(results, key=lambda x: x.get("total_num") or 0)[:5]
            remember_results(uid, cheapest, ctx.get("is_close", False), ctx.get("budget"))
            await update.message.reply_text(
                "دي أرخص اختيارات مؤكدة من الشيت:\n\n" + "\n\n---\n\n".join([fmt_unit(u) for u in cheapest]),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(NO_CONFIRMED_DATA)
        return

    if ctx.get("results") and dp:
        filtered = [x for x in ctx["results"] if dp.lower() in x["sheet"].lower()]
        if filtered:
            remember_project(uid, dp)
            remember_results(uid, filtered, ctx.get("is_close", False), ctx.get("budget"))
            await update.message.reply_text(
                "الوحدات في " + dp + ":\n\n" + "\n\n---\n\n".join([fmt_unit(x) for x in filtered[:5]]),
                parse_mode="Markdown"
            )
            return

    if is_data_request(msg):
        if dp:
            stats = project_stats(dp)
            await update.message.reply_text(fmt_stats(stats), parse_mode="Markdown")
        else:
            await update.message.reply_text(NO_CONFIRMED_DATA)
        return

    if not has_confirmed_context(uid):
        await update.message.reply_text(NO_CONFIRMED_DATA)
        return

    u = current_unit.get(uid)
    unit_ctx = "\nالوحدة الحالية المؤكدة من الشيت:\n" + fmt_unit(u) if u else ""
    results_ctx = "\nنتائج مؤكدة من الشيت: " + str(len(ctx.get("results", []))) + " وحدة." if ctx.get("results") else ""

    reply = ai(
        get_h(uid),
        system=SYSTEM_PROMPT + unit_ctx + results_ctx + " رد قصير بالمصري. استخدم البيانات المؤكدة فقط."
    )
    add_h(uid, "assistant", reply)
    await update.message.reply_text(reply)


def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

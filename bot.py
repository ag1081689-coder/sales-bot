import os
import json
import re
import logging
import anthropic
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
AV_SHEET_ID = "1f-1lkgr7nGiQofoREnhfbszjaJFu17OtZaMJ09_sLWw"
REQUIRED_ENV_VARS = ["GOOGLE_CREDENTIALS", "ANTHROPIC_API_KEY", "TELEGRAM_TOKEN", "SECRET_PASSWORD"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def validate_env():
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))

validate_env()
SECRET_PASSWORD = require_env("SECRET_PASSWORD")

PROJECTS = ["D11 BUSINESS", "D12 Medical", "METRO +", "TIJAN", "WW1", "WW2", "STAGE X", "RESALE", "MIDST"]

PROJECT_ALIASES = {
    "d11": "D11 BUSINESS", "d12": "D12 Medical",
    "ww1": "WW1", "ww2": "WW2", "tijan": "TIJAN",
    "midst": "MIDST", "stage x": "STAGE X",
    "resale": "RESALE", "metro": "METRO +",
}

SYSTEM_PROMPT = "ant msa3d mby3at fy sh3rkt m3mar dgla - kl almshary3 fy al3ashr mn rmdan - kl alwHdat edaryt aw tgaryt aw tbyt la skny - kl alm3lomat mn alshyt fqt la txtr3 ay arqam - rdd mxtsr wmbashr - HfZ 3la syaq alMHadtha - llbHth: PROJECT - UNIT CODE mthal WW1 - W1 C3 - llmyzanya: 3myl mqdmh X alf eGmaly mn Y l Z mlyon - lma txls: tmam"

creds_json = json.loads(require_env("GOOGLE_CREDENTIALS"))
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)
av_sh = gc.open_by_key(AV_SHEET_ID)
client = anthropic.Anthropic(api_key=require_env("ANTHROPIC_API_KEY"))

user_context = {}
chat_history = {}
current_unit = {}
headers_cache = {}

def clean(s):
    try: return float(re.sub(r'[^\d.]', '', str(s)))
    except Exception:
        logger.exception("Failed to clean numeric value: %r", s)
        return 0

def detect_project(text):
    t = text.lower()
    for a, r in PROJECT_ALIASES.items():
        if a in t: return r
    for p in PROJECTS:
        if p.lower() in t: return p
    return None

def parse_pu(text):
    if "-" in text:
        a, b = text.split("-", 1)
        p = detect_project(a.strip())
        if p and b.strip(): return p, b.strip().upper()
    return None, None

def get_headers(ws):
    if ws.title in headers_cache: return headers_cache[ws.title]
    h = {}
    for row in (ws.get_all_values() or [])[:3]:
        for i, c in enumerate(row):
            k = c.strip().lower().replace("_","")
            kc = k.replace(" ","")
            if kc in ["code","u."]: h["code"]=i
            elif kc == "area": h["area"]=i
            elif kc in ["price","pricepermeter"]: h["price"]=i
            elif kc == "status": h["status"]=i
            elif "totalpriceafterdi" in kc: h["total_after"]=i
            elif kc in ["totalprice","total"]:
                if "total_after" not in h: h["total"]=i
            elif "down" in kc and ("pay" in kc or kc == "down"): h["down"]=i
            elif kc in ["instalments","installments","batchafteryear","insta"]: h["inst"]=i
            elif kc in ["cashdiscount","discount"]: h["disc"]=i
            elif "delivery" in kc: h["delivery"]=i
    headers_cache[ws.title] = h
    return h

def gcell(row, h, k, d=""):
    i = h.get(k)
    return row[i].strip() if i is not None and i < len(row) else d

def get_status(row, h):
    i = h.get("status")
    if i is not None and i < len(row):
        v = row[i].strip().lower()
        if v in ["available","reserved","hold"]: return v
    for c in row:
        if c.strip().lower() in ["available","reserved","hold"]: return c.strip().lower()
    return ""

def row_to_unit(row, ws_title, h):
    bad = ["available","reserved","hold",""]
    total = gcell(row,h,"total_after") or gcell(row,h,"total")
    down = gcell(row,h,"down")
    return {
        "sheet": ws_title,
        "code": gcell(row,h,"code"),
        "area": gcell(row,h,"area"),
        "price": gcell(row,h,"price") if gcell(row,h,"price") not in bad else "",
        "total": total,
        "total_num": clean(total),
        "down": down if down not in bad else "",
        "down_num": clean(down),
        "inst": gcell(row,h,"inst") if gcell(row,h,"inst") not in bad else "",
        "delivery": gcell(row,h,"delivery") if gcell(row,h,"delivery") not in bad else "",
        "status": get_status(row,h)
    }

def find_unit(code, project=None):
    code = code.strip().upper().replace(" ","")
    for ws in av_sh.worksheets():
        if project and project.lower() not in ws.title.lower(): continue
        h = get_headers(ws)
        ci = h.get("code",0)
        for row in (ws.get_all_values() or [])[1:]:
            if row and row[ci].strip().upper().replace(" ","") == code:
                return row_to_unit(row, ws.title, h)
    return None

def search_budget(tmin, tmax, dmin=None, dmax=None, project=None):
    exact, close = [], []
    for ws in av_sh.worksheets():
        if project and project.lower() not in ws.title.lower(): continue
        h = get_headers(ws)
        ci = h.get("code",0)
        for row in (ws.get_all_values() or [])[1:]:
            if not row or not row[ci].strip(): continue
            if get_status(row,h) != "available": continue
            u = row_to_unit(row, ws.title, h)
            t, d = u["total_num"], u["down_num"]
            if t == 0: continue
            ok_t = tmin <= t <= tmax
            ok_d = (dmin is None or dmax is None) or (d == 0) or (dmin <= d <= dmax)
            if ok_t and ok_d: exact.append(u)
            elif tmin*0.8 <= t <= tmax*1.2: close.append(u)
    return exact, close

def project_stats(pfilter=None):
    res = {}
    for ws in av_sh.worksheets():
        if pfilter and pfilter.lower() not in ws.title.lower(): continue
        h = get_headers(ws)
        ci = h.get("code",0)
        cnt = {"available":0,"reserved":0,"hold":0}
        for row in (ws.get_all_values() or [])[1:]:
            if row and row[ci].strip():
                s = get_status(row,h)
                if s in cnt: cnt[s] += 1
        if sum(cnt.values()) > 0: res[ws.title] = cnt
    return res

def save_sale(project, unit, price, client_name):
    try:
        try: ws = sh.worksheet("المبيعات")
        except Exception:
            logger.info("Sales worksheet not found; creating it")
            ws = sh.add_worksheet("المبيعات", 1000, 10)
            ws.append_row(["المشروع","الوحدة","السعر","العميل","التاريخ"])
        from datetime import datetime
        ws.append_row([project, unit, price, client_name, datetime.now().strftime("%Y-%m-%d %H:%M")])
    except Exception:
        logger.exception("Failed to save sale for project=%r unit=%r", project, unit)

def get_sales():
    try:
        ws = sh.worksheet("المبيعات")
        data = ws.get_all_values()
        if len(data) <= 1: return "لا توجد مبيعات."
        return "\n".join([f"• {r[0]}-{r[1]}-{r[2]}-{r[3]}-{r[4]}" for r in data[1:] if len(r)>=4])
    except Exception:
        logger.exception("Failed to read sales worksheet")
        return "لا توجد مبيعات."

def fmt_unit(u):
    e = "✅" if u["status"]=="available" else "🔴" if u["status"]=="reserved" else "🔵"
    t = f"*{u['code']}* - {u['sheet']}\n"
    if u.get("area"): t += f"📐 {u['area']}م²\n"
    if u.get("price"): t += f"💰 سعر المتر: {u['price']} جنيه\n"
    if u.get("total"): t += f"💵 الإجمالي: {u['total']} جنيه\n"
    if u.get("down"): t += f"🔑 المقدم: {u['down']}\n"
    if u.get("delivery"): t += f"🏗️ التسليم: {u['delivery']}\n"
    if u.get("inst"): t += f"📅 الأقساط: {u['inst']}\n"
    t += f"{e} {u['status']}"
    return t

def fmt_stats(res):
    if not res: return "لا توجد بيانات."
    return "".join([f"📊 *{p}*\n✅{c['available']} 🔴{c['reserved']} 🔵{c['hold']} 📦{sum(c.values())}\n\n" for p,c in res.items()])

def fmt_plan(u, plan):
    return (f"💳 *Payment Plan - {u['code']}*\n"
            f"🏢 {u['sheet']} | 📐 {u.get('area','')}م²\n\n"
            f"💵 السعر: {plan['total']:,.0f} جنيه\n"
            f"🔑 المقدم {plan['dp']}%: {plan['down']:,.0f} جنيه\n"
            f"📊 المتبقي: {plan['rem']:,.0f} جنيه\n\n"
            f"على {plan['years']} سنين:\n"
            f"• ربع سنوي: {plan['q']:,.0f} جنيه\n"
            f"• شهري: {plan['m']:,.0f} جنيه")

def calc_plan(total_str, dp, years):
    try:
        t = clean(total_str)
        d = t*(dp/100); r = t-d
        return {"total":t,"down":d,"rem":r,"q":r/(years*4),"m":r/(years*12),"years":years,"dp":dp}
    except Exception:
        logger.exception("Failed to calculate payment plan for total=%r dp=%r years=%r", total_str, dp, years)
        return None

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
    "s_pain":("Pain Point","Start with client problem"),
    "s_compare":("المقارنة","Compare rent vs buy"),
    "s_fomo":("FOMO","Time pressure and scarcity"),
    "s_roi":("ROI","Calculate the return"),
    "s_story":("القصة","Success story"),
    "s_social":("Social Proof","Numbers and testimonials"),
    "s_exclusive":("Exclusivity","Exclusivity and scarcity"),
}

def add_h(uid, role, content):
    if uid not in chat_history: chat_history[uid] = []
    chat_history[uid].append({"role":role,"content":content})
    if len(chat_history[uid]) > 20: chat_history[uid] = chat_history[uid][-20:]

def get_h(uid): return chat_history.get(uid, [])

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
        "مرحباً! مساعدك في معمار دجلة\n\n"
        "وحدة: WW1 - W1 C3\n"
        "ميزانية: عميل مقدمه 500 ألف إجمالي من 2 ل 2.5 مليون\n"
        "Payment Plan: payment plan WW1 - W1 C3 مقدم 20% على 5 سنين\n"
        "لما تخلص: تمام"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    sk = q.data
    if sk not in STYLES: return
    sname, sinst = STYLES[sk]
    u = current_unit.get(uid)
    unit_data = fmt_unit(u) if u else ""
    reply = ai(
        [{"role":"user","content":"write script " + sname}],
        system=SYSTEM_PROMPT + " unit data: " + unit_data + " style: " + sname + " - " + sinst + " write whatsapp script in egyptian arabic based on unit data only.",
        max_tokens=800
    )
    await q.edit_message_text("*script " + sname + "*\n\n" + reply, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    uid = update.message.from_user.id
    ml = msg.lower()

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
            await update.message.reply_text("أدخل كلمة المرور:")
        return

    if "بيعة" in ml or "بعنا" in ml or "اتباع" in ml:
        try:
            t = ai([{"role":"user","content":msg}],
                   system='JSON only: {"action":"sale","project":"","unit":"","price":"","client":""}',
                   max_tokens=200)
            d = json.loads(t[t.find("{"):t.rfind("}")+1])
            if d.get("action") == "sale":
                save_sale(d["project"],d["unit"],d["price"],d["client"])
                current_unit.pop(uid, None)
                await update.message.reply_text("✅ " + d["project"] + " | " + d["unit"] + " | " + d["price"] + " | " + d["client"])
            return
        except Exception:
            logger.exception("Failed to parse or save sale message")

    if ml.strip() in ["تمام","ok","okay","تم","موافق","next"]:
        current_unit.pop(uid, None)
        user_context.pop(uid, None)
        await update.message.reply_text("تمام! في وحدة أو عميل تاني؟")
        return

    if "سكريبت" in ml:
        p, uc = parse_pu(msg)
        if p and uc:
            u = find_unit(uc, p)
            if u: current_unit[uid] = u
        u = current_unit.get(uid)
        if u:
            await update.message.reply_text("اختر الأسلوب:", reply_markup=style_buttons())
        else:
            await update.message.reply_text("ابعت الوحدة الأول، مثال: WW1 - W1 C3")
        return

    if "اعلان" in ml or "إعلان" in ml:
        u = current_unit.get(uid)
        unit_data = fmt_unit(u) if u else ""
        reply = ai([{"role":"user","content":msg}],
                   system=SYSTEM_PROMPT + " unit: " + unit_data + " write 3 ad variants in egyptian arabic based on data only.",
                   max_tokens=1000)
        await update.message.reply_text(reply)
        return

    if "payment plan" in ml or "بلان" in ml or "خطة سداد" in ml:
        p, uc = parse_pu(msg)
        u = find_unit(uc, p) if p and uc else current_unit.get(uid)
        if u:
            current_unit[uid] = u
            dp_m = re.search(r'(\d+)\s*%', msg)
            yr_m = re.search(r'(\d+)\s*سن', msg)
            plan = calc_plan(u["total"], int(dp_m.group(1)) if dp_m else 20, int(yr_m.group(1)) if yr_m else 5)
            if plan:
                add_h(uid,"user",msg)
                add_h(uid,"assistant","Payment Plan " + u["code"])
                await update.message.reply_text(fmt_plan(u, plan), parse_mode="Markdown")
                return
        await update.message.reply_text("ابعت الوحدة، مثال: payment plan WW1 - W1 C3 مقدم 20% على 5 سنين")
        return

    p, uc = parse_pu(msg)
    if p and uc:
        u = find_unit(uc, p)
        if u:
            current_unit[uid] = u
            add_h(uid,"user",msg)
            add_h(uid,"assistant","تفاصيل " + u["code"])
            await update.message.reply_text(fmt_unit(u), parse_mode="Markdown")
        else:
            await update.message.reply_text("مش لاقي " + uc + " في " + p)
        return

    if any(k in ml for k in ["مقدم","ميزانية","إجمالي","اجمالي","مليون","ألف","الف"]) and any(c.isdigit() for c in msg):
        try:
            t = ai([{"role":"user","content":msg}],
                   system='JSON only: {"total_min":0,"total_max":0,"down_min":null,"down_max":null} million=1000000 thousand=1000',
                   max_tokens=150)
            d = json.loads(t[t.find("{"):t.rfind("}")+1])
            tmin, tmax = d.get("total_min",0), d.get("total_max",0)
            if tmin > 0 and tmax > 0:
                dp = detect_project(msg)
                exact, close = search_budget(tmin, tmax, d.get("down_min"), d.get("down_max"), dp)
                add_h(uid,"user",msg)
                user_context[uid] = {
                    "budget": {"tmin":tmin,"tmax":tmax},
                    "results": exact or close,
                    "is_close": len(exact)==0
                }
                if exact:
                    parts = [fmt_unit(u) for u in exact[:15]]
                    out = "✅ *" + str(len(exact)) + " وحدة في النطاق:*\n\n" + "\n\n---\n\n".join(parts)
                    add_h(uid,"assistant","وجدت " + str(len(exact)) + " وحدة")
                elif close:
                    parts = [fmt_unit(u) for u in close[:15]]
                    out = "مفيش بالظبط، بس في " + str(len(close)) + " قريبة (20%):\n\n" + "\n\n---\n\n".join(parts)
                    add_h(uid,"assistant","وجدت " + str(len(close)) + " قريبة")
                else:
                    out = "مفيش وحدات في النطاق ده. جرب توسع النطاق."
                await update.message.reply_text(out, parse_mode="Markdown")
                return
        except Exception:
            logger.exception("Failed to parse budget message")

    dp = detect_project(msg)
    if any(k in ml for k in ["كام وحدة","كل المشاريع","جميع","إتاحة","اتاحه","احصائيه"]):
        await update.message.reply_text(fmt_stats(project_stats(dp)), parse_mode="Markdown")
        return

    add_h(uid,"user",msg)
    u = current_unit.get(uid)
    ctx = user_context.get(uid, {})

    if ctx.get("results") and dp:
        filtered = [x for x in ctx["results"] if dp.lower() in x["sheet"].lower()]
        if filtered:
            parts = [fmt_unit(x) for x in filtered[:5]]
            out = "الوحدات في " + dp + ":\n\n" + "\n\n---\n\n".join(parts)
            await update.message.reply_text(out, parse_mode="Markdown")
            add_h(uid,"assistant","وحدات " + dp)
            return

    unit_ctx = "\nالوحدة الحالية:\n" + fmt_unit(u) + "\nتكلم بس عن البيانات دي." if u else ""
    budget_ctx = "\nنتائج البحث: " + str(len(ctx.get("results",[]))) + " وحدة." if ctx.get("results") else ""

    reply = ai(get_h(uid), system=SYSTEM_PROMPT + unit_ctx + budget_ctx)
    add_h(uid,"assistant",reply)
    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(require_env("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

import os
import json
import re
import anthropic
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
AV_SHEET_ID = "1f-1lkgr7nGiQofoREnhfbszjaJFu17OtZaMJ09_sLWw"
SECRET_PASSWORD = os.environ.get("SECRET_PASSWORD", "Adel2026")

PROJECTS = ["D11 BUSINESS", "D12 Medical", "METRO +", "TIJAN", "WW1", "WW2", "STAGE X", "RESALE", "MIDST"]

PROJECT_ALIASES = {
    "d11": "D11 BUSINESS", "d11 business": "D11 BUSINESS",
    "d12": "D12 Medical", "d12 medical": "D12 Medical",
    "ww1": "WW1", "waterway 1": "WW1",
    "ww2": "WW2", "waterway 2": "WW2",
    "tijan": "TIJAN", "midst": "MIDST",
    "stage x": "STAGE X", "stagex": "STAGE X",
    "resale": "RESALE", "metro": "METRO +",
    "metro +": "METRO +", "metro plus": "METRO +",
}

COMPANY_CONTEXT = """
شركة معمار دجلة للتطوير العقاري - كل مشاريعها في العاشر من رمضان.
جميع الوحدات إدارية أو تجارية أو طبية - لا توجد وحدات سكنية.
المشاريع: D11 BUSINESS, D12 Medical, METRO +, TIJAN, WW1, WW2, STAGE X, RESALE, MIDST
مهم جداً: لا تخترع أي معلومات - كل البيانات تيجي من الشيت فقط.
"""

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)
av_sh = gc.open_by_key(AV_SHEET_ID)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

user_context = {}
chat_history = {}
current_unit = {}  # يحفظ الوحدة الحالية لكل يوزر
sheet_headers_cache = {}

def get_sheet_headers(ws):
    if ws.title in sheet_headers_cache:
        return sheet_headers_cache[ws.title]
    data = ws.get_all_values()
    if not data:
        return {}
    headers = {}
    for row in data[:3]:
        for i, cell in enumerate(row):
            c = cell.strip().lower().replace(" ", "").replace("_", "")
            if c in ["code", "u."]: headers["code"] = i
            elif c == "area": headers["area"] = i
            elif c in ["price", "pricepermeter"]: headers["price"] = i
            elif c == "status": headers["status"] = i
            elif "totalpriceafterdi" in c: headers["total_after"] = i
            elif c in ["totalprice", "total"]:
                if "total_after" not in headers: headers["total"] = i
            elif c in ["downpayment", "down"]: headers["downpayment"] = i
            elif c in ["instalments", "installments", "batchafteryear"]: headers["installments"] = i
            elif c in ["cashdiscount", "discount"]: headers["discount"] = i
            elif c in ["deliverypayment", "delivery"]: headers["delivery"] = i
    sheet_headers_cache[ws.title] = headers
    return headers

def get_cell(row, headers, key, default=""):
    idx = headers.get(key)
    if idx is not None and idx < len(row):
        return row[idx].strip()
    return default

def get_status_from_row(row, headers):
    status_idx = headers.get("status")
    if status_idx is not None and status_idx < len(row):
        val = row[status_idx].strip().lower()
        if val in ["available", "reserved", "hold"]:
            return val
    for cell in row:
        if cell.strip().lower() in ["available", "reserved", "hold"]:
            return cell.strip().lower()
    return ""

def clean_number(s):
    try:
        return float(re.sub(r'[^\d.]', '', str(s)))
    except:
        return 0

def detect_project(text):
    text_lower = text.lower().strip()
    for alias, real in PROJECT_ALIASES.items():
        if alias in text_lower:
            return real
    for p in PROJECTS:
        if p.lower() in text_lower:
            return p
    return None

def extract_area(text):
    patterns = [r'(\d+)\s*متر', r'(\d+)\s*م²', r'مساحت[هة]\s*(\d+)']
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None

def parse_project_unit(text):
    if "-" in text:
        parts = text.split("-", 1)
        detected = detect_project(parts[0].strip())
        if detected and parts[1].strip():
            return detected, parts[1].strip().upper()
    return None, None

def get_unit_from_sheet(unit_code, project_filter=None):
    try:
        search_code = unit_code.strip().upper().replace(" ", "")
        for ws in av_sh.worksheets():
            if project_filter and project_filter.lower() not in ws.title.lower():
                continue
            data = ws.get_all_values()
            if not data:
                continue
            headers = get_sheet_headers(ws)
            code_idx = headers.get("code", 0)
            for row in data[1:]:
                if not row or not row[code_idx].strip():
                    continue
                if row[code_idx].strip().upper().replace(" ", "") == search_code:
                    return {
                        "sheet": ws.title,
                        "code": get_cell(row, headers, "code"),
                        "area": get_cell(row, headers, "area"),
                        "price": get_cell(row, headers, "price"),
                        "total": get_cell(row, headers, "total_after") or get_cell(row, headers, "total"),
                        "downpayment": get_cell(row, headers, "downpayment"),
                        "installments": get_cell(row, headers, "installments"),
                        "delivery": get_cell(row, headers, "delivery"),
                        "status": get_status_from_row(row, headers)
                    }
        return None
    except:
        return None

def search_units_by_budget(total_min, total_max, down_min=None, down_max=None):
    results = []
    close_results = []
    for ws in av_sh.worksheets():
        data = ws.get_all_values()
        if not data:
            continue
        headers = get_sheet_headers(ws)
        code_idx = headers.get("code", 0)
        for row in data[1:]:
            if not row or not row[code_idx].strip():
                continue
            status = get_status_from_row(row, headers)
            if status != "available":
                continue
            total_str = get_cell(row, headers, "total_after") or get_cell(row, headers, "total")
            down_str = get_cell(row, headers, "downpayment")
            total = clean_number(total_str)
            down = clean_number(down_str)
            if total == 0:
                continue
            unit = {
                "sheet": ws.title,
                "code": get_cell(row, headers, "code"),
                "area": get_cell(row, headers, "area"),
                "price": get_cell(row, headers, "price"),
                "total": total_str,
                "total_num": total,
                "downpayment": down_str,
                "down_num": down,
                "installments": get_cell(row, headers, "installments"),
                "status": status
            }
            in_total = total_min <= total <= total_max
            in_down = True
            if down_min is not None and down_max is not None and down > 0:
                in_down = down_min <= down <= down_max
            if in_total and in_down:
                results.append(unit)
            elif total_min * 0.8 <= total <= total_max * 1.2:
                close_results.append(unit)
    return results, close_results

def get_project_status(project_filter=None):
    try:
        results = {}
        for ws in av_sh.worksheets():
            if project_filter and project_filter.lower() not in ws.title.lower():
                continue
            data = ws.get_all_values()
            headers = get_sheet_headers(ws)
            counts = {"available": 0, "reserved": 0, "hold": 0}
            for row in data[1:]:
                if not row or not row[0].strip():
                    continue
                s = get_status_from_row(row, headers)
                if s in counts:
                    counts[s] += 1
            if sum(counts.values()) > 0:
                results[ws.title] = counts
        return results
    except:
        return {}

def get_all_units(project_filter=None, status_filter=None, area_filter=None):
    try:
        all_units = []
        for ws in av_sh.worksheets():
            if project_filter and project_filter.lower() not in ws.title.lower():
                continue
            data = ws.get_all_values()
            headers = get_sheet_headers(ws)
            code_idx = headers.get("code", 0)
            for row in data[1:]:
                if not row or not row[code_idx].strip():
                    continue
                row_status = get_status_from_row(row, headers)
                if not row_status or row_status not in ["available", "reserved", "hold"]:
                    continue
                if status_filter and row_status != status_filter.lower():
                    continue
                area = get_cell(row, headers, "area")
                if area_filter:
                    try:
                        if abs(float(area.replace(",", "")) - area_filter) > 2:
                            continue
                    except:
                        continue
                total = get_cell(row, headers, "total_after") or get_cell(row, headers, "total")
                all_units.append({
                    "sheet": ws.title,
                    "code": get_cell(row, headers, "code"),
                    "area": area,
                    "total": total,
                    "downpayment": get_cell(row, headers, "downpayment"),
                    "status": row_status
                })
        return all_units
    except:
        return []

def calculate_payment_plan(total_price_str, down_pct, years):
    try:
        total = clean_number(total_price_str)
        down = total * (down_pct / 100)
        remaining = total - down
        quarterly = remaining / (years * 4)
        monthly = remaining / (years * 12)
        return {"total": total, "down": down, "remaining": remaining,
                "quarterly": quarterly, "monthly": monthly, "years": years, "down_pct": down_pct}
    except:
        return None

def format_payment_plan(unit, plan):
    text = f"💳 *Payment Plan - {unit['code']}*\n"
    text += f"🏢 {unit['sheet']} | 📐 {unit.get('area', '')}م²\n\n"
    text += f"💵 السعر: {plan['total']:,.0f} جنيه\n"
    text += f"🔑 المقدم {plan['down_pct']}%: {plan['down']:,.0f} جنيه\n"
    text += f"📊 المتبقي: {plan['remaining']:,.0f} جنيه\n\n"
    text += f"على {plan['years']} سنين:\n"
    text += f"• ربع سنوي: {plan['quarterly']:,.0f} جنيه\n"
    text += f"• شهري: {plan['monthly']:,.0f} جنيه"
    return text

def format_unit_card(unit):
    bad = ["available", "reserved", "hold", ""]
    status_emoji = "✅" if unit.get("status") == "available" else "🔴" if unit.get("status") == "reserved" else "🔵"
    text = f"🏢 *{unit['code']}* - {unit['sheet']}\n"
    if unit.get("area"): text += f"📐 {unit['area']}م²\n"
    if unit.get("price") and unit.get("price") not in bad: text += f"💰 سعر المتر: {unit['price']} جنيه\n"
    if unit.get("total") and unit.get("total") not in bad: text += f"💵 الإجمالي: {unit['total']} جنيه\n"
    if unit.get("downpayment") and unit.get("downpayment") not in bad: text += f"🔑 المقدم: {unit['downpayment']}\n"
    if unit.get("installments") and unit.get("installments") not in bad: text += f"📅 الأقساط: {unit['installments']}\n"
    text += f"{status_emoji} {unit.get('status', '')}"
    return text

def format_status(results):
    if not results: return "لا توجد بيانات."
    text = ""
    for project, counts in results.items():
        total = sum(counts.values())
        text += f"📊 *{project}*\n✅ {counts['available']} | 🔴 {counts['reserved']} | 🔵 {counts['hold']} | 📦 {total}\n\n"
    return text

def format_units_list(units, title=""):
    if not units: return "لا توجد وحدات."
    result = f"*{title}*\n\n" if title else ""
    current_sheet = ""
    for u in units[:20]:
        if u["sheet"] != current_sheet:
            current_sheet = u["sheet"]
            result += f"*{current_sheet}:*\n"
        e = "✅" if u["status"] == "available" else "🔴" if u["status"] == "reserved" else "🔵"
        result += f"• {u['code']} | {u['area']}م² | {u['total']} | {e}\n"
    return result

def save_sale(project, unit, price, client_name):
    try:
        try:
            ws = sh.worksheet("المبيعات")
        except:
            ws = sh.add_worksheet(title="المبيعات", rows=1000, cols=10)
            ws.append_row(["المشروع", "الوحدة", "السعر", "اسم العميل", "التاريخ"])
        from datetime import datetime
        ws.append_row([project, unit, price, client_name, datetime.now().strftime("%Y-%m-%d %H:%M")])
        return True
    except:
        return False

def get_sales_data():
    try:
        ws = sh.worksheet("المبيعات")
        data = ws.get_all_values()
        if len(data) <= 1: return "لا توجد مبيعات مسجلة حتى الآن."
        return "\n".join([f"• {r[0]} - {r[1]} - {r[2]} - {r[3]} - {r[4]}" for r in data[1:] if len(r) >= 4])
    except:
        return "لا توجد مبيعات مسجلة."

def get_project_info(project_name):
    try:
        ws = sh.worksheet(project_name)
        data = ws.get_all_values()
        return "\n".join([f"{r[0]}: {r[1]}" for r in data[1:] if len(r) >= 2 and r[0] and r[1]])
    except:
        return ""

def get_style_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("😣 Pain Point", callback_data="style_pain"),
         InlineKeyboardButton("📊 المقارنة", callback_data="style_compare")],
        [InlineKeyboardButton("⏰ FOMO", callback_data="style_fomo"),
         InlineKeyboardButton("💰 ROI والأرقام", callback_data="style_roi")],
        [InlineKeyboardButton("📖 القصة", callback_data="style_story"),
         InlineKeyboardButton("⭐ Social Proof", callback_data="style_social")],
        [InlineKeyboardButton("💎 Exclusivity", callback_data="style_exclusive")]
    ])

STYLES = {
    "style_pain": ("Pain Point", "ابدأ بمشكلة العميل"),
    "style_compare": ("المقارنة", "قارن بين الإيجار والشراء"),
    "style_fomo": ("FOMO", "ضغط الوقت والندرة"),
    "style_roi": ("ROI والأرقام", "احسبله العائد"),
    "style_story": ("القصة", "قصة عميل نجح"),
    "style_social": ("Social Proof", "أرقام وشهادات"),
    "style_exclusive": ("Exclusivity", "الحصرية والندرة")
}

def add_to_history(user_id, role, content):
    if user_id not in chat_history:
        chat_history[user_id] = []
    chat_history[user_id].append({"role": role, "content": content})
    if len(chat_history[user_id]) > 30:
        chat_history[user_id] = chat_history[user_id][-30:]

def get_history(user_id):
    return chat_history.get(user_id, [])

def set_current_unit(user_id, unit):
    current_unit[user_id] = unit

def get_current_unit(user_id):
    return current_unit.get(user_id)

def clear_current_unit(user_id):
    if user_id in current_unit:
        del current_unit[user_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_history[user_id] = []
    clear_current_unit(user_id)
    await update.message.reply_text(
        "مرحباً! أنا مساعدك الذكي في معمار دجلة 🏢\n\n"
        "كلمني بشكل طبيعي وأنا هساعدك.\n"
        "• للبحث عن وحدة: WW1 - W1 C3\n"
        "• للميزانية: عميل مقدمه 500 ألف إجمالي من 2 ل 2.5 مليون\n"
        "• للـ Payment Plan: payment plan WW1 - W1 C3 مقدم 20% على 5 سنين"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    style_key = query.data
    if style_key not in STYLES:
        return
    style_name, style_instruction = STYLES[style_key]
    saved = user_context.get(user_id, {})
    project = saved.get("project", "")
    project_info = get_project_info(project) if project else ""
    request = saved.get("request", "")
    unit = get_current_unit(user_id)
    unit_context = f"\nالوحدة الحالية: {json.dumps(unit, ensure_ascii=False)}" if unit else ""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=800,
        system=f"أنت خبير تسويق عقاري في معمار دجلة.\n{COMPANY_CONTEXT}\nمعلومات: {project_info}{unit_context}\nتفاصيل: {request}\nالأسلوب: {style_name} - {style_instruction}\nاكتب سكريبت واتساب بأسلوب مصري راقٍ.",
        messages=[{"role": "user", "content": f"اكتب سكريبت {style_name} لمشروع {project}"}]
    )
    await query.edit_message_text(f"*سكريبت {style_name} - {project}*\n\n{response.content[0].text}", parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    user_id = update.message.from_user.id
    msg_lower = user_message.lower()

    # كلمة المرور
    if user_context.get(user_id, {}).get("waiting_password"):
        if user_message == SECRET_PASSWORD:
            user_context[user_id] = {"authenticated": True}
            await update.message.reply_text(f"سجل المبيعات:\n\n{get_sales_data()}")
        else:
            await update.message.reply_text("كلمة المرور غير صحيحة.")
        return

    if "مبيعات" in msg_lower or "بايعين" in msg_lower:
        if user_context.get(user_id, {}).get("authenticated"):
            await update.message.reply_text(f"سجل المبيعات:\n\n{get_sales_data()}")
        else:
            user_context[user_id] = {"waiting_password": True}
            await update.message.reply_text("من فضلك أدخل كلمة المرور:")
        return

    # تسجيل بيعة
    if "بيعة" in msg_lower or "بعنا" in msg_lower or "اتباع" in msg_lower:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            system='استخرج معلومات البيعة وأرجع JSON فقط: {"action":"sale","project":"اسم","unit":"وحدة","price":"سعر","client":"عميل"}',
            messages=[{"role": "user", "content": user_message}]
        )
        try:
            reply = response.content[0].text.strip()
            data = json.loads(reply[reply.find("{"):reply.rfind("}")+1])
            if data.get("action") == "sale":
                save_sale(data["project"], data["unit"], data["price"], data["client"])
                clear_current_unit(user_id)
                await update.message.reply_text(f"✅ تم تسجيل البيعة\n{data['project']} | {data['unit']} | {data['price']} | {data['client']}")
            return
        except:
            pass

    # تمام = مسح الوحدة الحالية
    if msg_lower.strip() in ["تمام", "ok", "okay", "تم", "موافق"]:
        clear_current_unit(user_id)
        await update.message.reply_text("تمام! في أي وحدة أو عميل تاني؟")
        return

    # Payment Plan
    if "payment plan" in msg_lower or "بلان" in msg_lower or "خطة سداد" in msg_lower:
        unit = get_current_unit(user_id)
        detected_project, unit_code = parse_project_unit(user_message)

        if detected_project and unit_code:
            unit = get_unit_from_sheet(unit_code, detected_project)
            if unit:
                set_current_unit(user_id, unit)

        if unit:
            total_str = unit.get("total", "0")
            down_match = re.search(r'(\d+)\s*%', user_message)
            years_match = re.search(r'(\d+)\s*سن', user_message)
            down_pct = int(down_match.group(1)) if down_match else 20
            years = int(years_match.group(1)) if years_match else 5
            plan = calculate_payment_plan(total_str, down_pct, years)
            if plan:
                add_to_history(user_id, "user", user_message)
                add_to_history(user_id, "assistant", f"Payment Plan للوحدة {unit['code']}")
                await update.message.reply_text(format_payment_plan(unit, plan), parse_mode="Markdown")
                return

    # البحث بالكود المباشر
    detected_project, unit_code = parse_project_unit(user_message)
    if detected_project and unit_code:
        unit = get_unit_from_sheet(unit_code, detected_project)
        if unit:
            set_current_unit(user_id, unit)
            add_to_history(user_id, "user", user_message)
            add_to_history(user_id, "assistant", f"تفاصيل الوحدة {unit['code']}")
            await update.message.reply_text(format_unit_card(unit), parse_mode="Markdown")
        else:
            await update.message.reply_text(f"مش لاقي الوحدة {unit_code} في {detected_project}")
        return

    # البحث بالميزانية
    budget_keywords = ["مقدم", "ميزانية", "إجمالي", "اجمالي", "مليون", "ألف", "الف", "عميل معاه"]
    if any(k in msg_lower for k in budget_keywords) and any(c.isdigit() for c in user_message):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            system="""استخرج نطاق الميزانية وأرجع JSON فقط:
{"total_min": رقم, "total_max": رقم, "down_min": رقم أو null, "down_max": رقم أو null}
مليون = 1000000، ألف = 1000""",
            messages=[{"role": "user", "content": user_message}]
        )
        try:
            reply = response.content[0].text.strip()
            data = json.loads(reply[reply.find("{"):reply.rfind("}")+1])
            total_min = data.get("total_min", 0)
            total_max = data.get("total_max", 0)
            down_min = data.get("down_min")
            down_max = data.get("down_max")

            if total_min > 0 and total_max > 0:
                exact_units, close_units = search_units_by_budget(total_min, total_max, down_min, down_max)
                add_to_history(user_id, "user", user_message)

                if exact_units:
                    msg = f"✅ *وجدت {len(exact_units)} وحدة في نطاق الميزانية:*\n\n"
                    for u in exact_units[:5]:
                        msg += format_unit_card(u) + "\n\n---\n\n"
                    add_to_history(user_id, "assistant", f"وجدت {len(exact_units)} وحدة في النطاق")
                    await update.message.reply_text(msg, parse_mode="Markdown")
                elif close_units:
                    msg = f"مفيش بالظبط في النطاق ده، بس عندي أقرب خيارات (±20%):\n\n"
                    for u in close_units[:5]:
                        msg += format_unit_card(u) + "\n\n---\n\n"
                    add_to_history(user_id, "assistant", f"وجدت {len(close_units)} وحدة قريبة من النطاق")
                    await update.message.reply_text(msg, parse_mode="Markdown")
                else:
                    await update.message.reply_text("مفيش وحدات في النطاق ده دلوقتي. جرب توسع النطاق.")
                return
        except:
            pass

    detected_project = detect_project(user_message)
    area_filter = extract_area(user_message)

    keywords_all = ["كل المشاريع", "كل حاجه", "الكل", "جميع"]
    keywords_status = ["كام وحدة", "وحدات متاح", "reserved", "hold", "احصائيه", "إتاحة", "اتاحه"]

    if any(k in msg_lower for k in keywords_all) and not detected_project:
        await update.message.reply_text(f"📊 *ملخص جميع المشاريع*\n\n{format_status(get_project_status())}", parse_mode="Markdown")
        return

    if any(k in msg_lower for k in keywords_status):
        status_filter = "available" if "متاح" in msg_lower or "available" in msg_lower or "فاضي" in msg_lower else \
                       "reserved" if "reserved" in msg_lower or "محجوز" in msg_lower else \
                       "hold" if "hold" in msg_lower else None
        units = get_all_units(detected_project, status_filter, area_filter)
        title = f"الوحدات{' ' + status_filter if status_filter else ''}{' في ' + detected_project if detected_project else ''}"
        await update.message.reply_text(format_units_list(units, title), parse_mode="Markdown")
        return

    if "سكريبت" in msg_lower:
        user_context[user_id] = {"project": detected_project or "", "request": user_message}
        await update.message.reply_text(f"سكريبت {detected_project or ''} - اختر الأسلوب:", reply_markup=get_style_buttons())
        return

    if "اعلان" in msg_lower or "إعلان" in msg_lower:
        project_info = get_project_info(detected_project) if detected_project else ""
        response = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1200,
            system=f"أنت خبير تسويق عقاري في معمار دجلة.\n{COMPANY_CONTEXT}\nمعلومات المشروع: {project_info}\nاكتب 3 صيغ إعلانية بأسلوب مصري راقٍ.",
            messages=[{"role": "user", "content": user_message}]
        )
        await update.message.reply_text(response.content[0].text)
        return

    # المحادثة الذكية مع حفظ السياق
    add_to_history(user_id, "user", user_message)

    unit = get_current_unit(user_id)
    unit_context = f"\nالوحدة الحالية التي نتحدث عنها: {json.dumps(unit, ensure_ascii=False)}\nلا تتغير عن هذه الوحدة إلا لما يقول السيلز 'تمام' أو يطلب وحدة تانية." if unit else ""

    system = f"""أنت مساعد مبيعات ذكي في معمار دجلة.
{COMPANY_CONTEXT}
{unit_context}
قواعد مهمة:
- كل المعلومات تيجي من الشيت فقط - لا تخترع أي أرقام أو معلومات
- لو مش عارف حاجة قول "مش عندي المعلومة دي في الشيت"
- حافظ على سياق المحادثة ومتنساش اللي اتقاله
- لو السيلز بيسأل عن نفس الوحدة استمر في الكلام عنها
- أجب بشكل مختصر وعملي بأسلوب مصري راقٍ"""

    history = get_history(user_id)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=500,
        system=system, messages=history
    )
    reply = response.content[0].text.strip()
    add_to_history(user_id, "assistant", reply)
    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

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

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)
av_sh = gc.open_by_key(AV_SHEET_ID)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

user_context = {}
chat_history = {}
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
        project_part = parts[0].strip()
        unit_part = parts[1].strip()
        detected = detect_project(project_part)
        if detected and unit_part:
            return detected, unit_part.upper()
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
                        "discount": get_cell(row, headers, "discount"),
                        "total": get_cell(row, headers, "total"),
                        "total_after": get_cell(row, headers, "total_after"),
                        "downpayment": get_cell(row, headers, "downpayment"),
                        "installments": get_cell(row, headers, "installments"),
                        "delivery": get_cell(row, headers, "delivery"),
                        "status": get_status_from_row(row, headers)
                    }
        return None
    except:
        return None

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
        total = float(re.sub(r'[^\d.]', '', total_price_str))
        down = total * (down_pct / 100)
        remaining = total - down
        quarters = years * 4
        quarterly = remaining / quarters if quarters > 0 else 0
        monthly = remaining / (years * 12) if years > 0 else 0
        return {
            "total": total,
            "down": down,
            "remaining": remaining,
            "quarterly": quarterly,
            "monthly": monthly,
            "years": years,
            "down_pct": down_pct
        }
    except:
        return None

def format_payment_plan(unit, plan):
    text = f"💳 *Payment Plan - {unit['code']}*\n"
    text += f"🏢 المشروع: {unit['sheet']}\n"
    text += f"📐 المساحة: {unit['area']}م²\n\n"
    text += f"💵 السعر الإجمالي: {plan['total']:,.0f} جنيه\n"
    text += f"🔑 المقدم {plan['down_pct']}%: {plan['down']:,.0f} جنيه\n"
    text += f"📊 المتبقي: {plan['remaining']:,.0f} جنيه\n\n"
    text += f"على {plan['years']} سنين:\n"
    text += f"• قسط ربع سنوي: {plan['quarterly']:,.0f} جنيه\n"
    text += f"• قسط شهري: {plan['monthly']:,.0f} جنيه\n"
    return text

def format_unit_details(unit):
    status_emoji = "✅" if unit["status"] == "available" else "🔴" if unit["status"] == "reserved" else "🔵"
    text = f"*{unit['code']}* - {unit['sheet']}\n\n"
    if unit.get("area"):
        text += f"📐 المساحة: {unit['area']}م²\n"
    price = unit.get("price", "")
    if price and price not in ["available", "reserved", "hold"]:
        text += f"💰 سعر المتر: {price} جنيه\n"
    if unit.get("total_after") and unit.get("total_after") not in ["available", "reserved", "hold"]:
        text += f"✨ السعر بعد الخصم: {unit['total_after']} جنيه\n"
    elif unit.get("total") and unit.get("total") not in ["available", "reserved", "hold"]:
        text += f"💵 السعر: {unit['total']} جنيه\n"
    if unit.get("downpayment") and unit.get("downpayment") not in ["available", "reserved", "hold"]:
        text += f"🔑 المقدم: {unit['downpayment']}\n"
    if unit.get("installments") and unit.get("installments") not in ["available", "reserved", "hold"]:
        text += f"📅 الأقساط: {unit['installments']}\n"
    text += f"📊 الحالة: {status_emoji} {unit['status']}"
    return text

def format_status(results):
    if not results:
        return "لا توجد بيانات."
    text = ""
    for project, counts in results.items():
        total = sum(counts.values())
        text += f"📊 *{project}*\n✅ {counts['available']} | 🔴 {counts['reserved']} | 🔵 {counts['hold']} | 📦 {total}\n\n"
    return text

def format_units(units, title=""):
    if not units:
        return "لا توجد وحدات بهذه المواصفات."
    result = f"*{title}*\n\n" if title else ""
    current_sheet = ""
    for u in units[:25]:
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
        if len(data) <= 1:
            return "لا توجد مبيعات مسجلة حتى الآن."
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
    if len(chat_history[user_id]) > 20:
        chat_history[user_id] = chat_history[user_id][-20:]

def get_history(user_id):
    return chat_history.get(user_id, [])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    chat_history[user_id] = []
    await update.message.reply_text(
        "مرحباً! أنا مساعدك الذكي في معمار دجلة 🏢\n\n"
        "كلمني بشكل طبيعي وأنا هساعدك.\n"
        "للبحث عن وحدة: WW1 - W1 C3\n"
        "للـ Payment Plan: payment plan WW1 - W1 C3 مقدم 20% على 5 سنين"
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
    request = saved.get("request", "")
    project_info = get_project_info(project) if project else ""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=f"""أنت خبير تسويق عقاري في معمار دجلة.
معلومات المشروع: {project_info}
تفاصيل: {request}
الأسلوب: {style_name} - {style_instruction}
اكتب سكريبت واتساب بأسلوب مصري راقٍ. لا تذكر غير معمار دجلة.""",
        messages=[{"role": "user", "content": f"اكتب سكريبت {style_name} لمشروع {project}"}]
    )
    await query.edit_message_text(
        f"*سكريبت {style_name} - {project}*\n\n{response.content[0].text}",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    user_id = update.message.from_user.id
    msg_lower = user_message.lower()

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
                await update.message.reply_text(f"✅ تم تسجيل البيعة\n{data['project']} | {data['unit']} | {data['price']} | {data['client']}")
            return
        except:
            pass

    # Payment Plan
    if "payment plan" in msg_lower or "بلان" in msg_lower or "خطة سداد" in msg_lower:
        detected_project, unit_code = parse_project_unit(user_message)
        if detected_project and unit_code:
            unit = get_unit_from_sheet(unit_code, detected_project)
            if unit:
                total_str = unit.get("total_after") or unit.get("total", "0")
                down_match = re.search(r'(\d+)\s*%', user_message)
                years_match = re.search(r'(\d+)\s*سن', user_message)
                down_pct = int(down_match.group(1)) if down_match else 20
                years = int(years_match.group(1)) if years_match else 5
                plan = calculate_payment_plan(total_str, down_pct, years)
                if plan:
                    text = format_payment_plan(unit, plan)
                    await update.message.reply_text(text, parse_mode="Markdown")
                    return

        # لو مفيش كود محدد اسأل Claude يحسب
        response = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=600,
            system="أنت مساعد مبيعات عقاري في معمار دجلة. احسب خطة السداد بالأرقام بشكل واضح ومنظم.",
            messages=[{"role": "user", "content": user_message}]
        )
        await update.message.reply_text(response.content[0].text)
        return

    # البحث عن وحدة
    detected_project, unit_code = parse_project_unit(user_message)
    if detected_project and unit_code:
        unit = get_unit_from_sheet(unit_code, detected_project)
        if unit:
            await update.message.reply_text(format_unit_details(unit), parse_mode="Markdown")
        else:
            await update.message.reply_text(f"مش لاقي الوحدة {unit_code} في {detected_project}")
        return

    detected_project = detect_project(user_message)
    area_filter = extract_area(user_message)

    keywords_all = ["كل المشاريع", "كل حاجه", "الكل", "جميع"]
    keywords_status = ["كام وحدة", "وحدات", "متاح", "reserved", "hold", "احصائيه", "كام", "إتاحة", "اتاحه"]
    keywords_available = ["متاح", "available", "فاضي"]

    if any(k in msg_lower for k in keywords_all) and not detected_project:
        text = format_status(get_project_status())
        await update.message.reply_text(f"📊 *ملخص جميع المشاريع*\n\n{text}", parse_mode="Markdown")
        return

    if any(k in msg_lower for k in keywords_status):
        status_filter = "available" if any(k in msg_lower for k in keywords_available) else \
                       "reserved" if "reserved" in msg_lower or "محجوز" in msg_lower else \
                       "hold" if "hold" in msg_lower else None
        if area_filter or status_filter or detected_project:
            units = get_all_units(detected_project, status_filter, area_filter)
            title = f"الوحدات{' ' + status_filter if status_filter else ''}{' (' + str(area_filter) + 'م²)' if area_filter else ''}{' في ' + detected_project if detected_project else ''}"
            await update.message.reply_text(format_units(units, title), parse_mode="Markdown")
        else:
            await update.message.reply_text(f"📊 *ملخص المشاريع*\n\n{format_status(get_project_status())}", parse_mode="Markdown")
        return

    if "سكريبت" in msg_lower:
        user_context[user_id] = {"project": detected_project or "", "request": user_message}
        await update.message.reply_text(f"سكريبت {detected_project or ''} - اختر الأسلوب:", reply_markup=get_style_buttons())
        return

    if "اعلان" in msg_lower or "إعلان" in msg_lower:
        project_info = get_project_info(detected_project) if detected_project else ""
        response = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1200,
            system=f"أنت خبير تسويق عقاري في معمار دجلة.\nمعلومات المشروع: {project_info}\nاكتب 3 صيغ إعلانية بأسلوب مصري راقٍ.",
            messages=[{"role": "user", "content": user_message}]
        )
        await update.message.reply_text(response.content[0].text)
        return

    # المحادثة الذكية
    add_to_history(user_id, "user", user_message)

    units_context = ""
    if detected_project or area_filter:
        units = get_all_units(project_filter=detected_project, status_filter="available", area_filter=area_filter)
        if units:
            units_context = f"\nالوحدات المتاحة:\n" + "\n".join([f"• {u['code']} | {u['area']}م² | {u['total']}" for u in units[:10]])

    system = f"""أنت مساعد مبيعات ذكي في شركة معمار دجلة.
تتحدث بأسلوب مصري راقٍ وطبيعي - مش روبوت، بتتناقش وبتساعد.
جميع الوحدات إدارية أو تجارية أو طبية - لا توجد سكنية.
المشاريع: {", ".join(PROJECTS)}
{units_context}
للبحث عن وحدة: PROJECT - UNIT CODE (مثال: WW1 - W1 C3)
للـ payment plan: payment plan PROJECT - UNIT مقدم X% على Y سنين
ساعد السيلز يلاقي الوحدة المناسبة واسأل عن احتياجات العميل."""

    history = get_history(user_id)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=system,
        messages=history
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

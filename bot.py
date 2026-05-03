import os
import json
import anthropic
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
AV_SHEET_ID = "1f-1lkgr7nGiQofoREnhfbszjaJFu17OtZaMJ09_sLWw"
SECRET_PASSWORD = os.environ.get("SECRET_PASSWORD", "Adel2026")

PROJECTS = ["D11 BUSINESS", "D12 Medical", "Metro Degla", "Medist", "Tigan", "WW1", "WW2", "STAGE X", "RESALE", "MIDST", "TIJAN"]

PROJECT_ALIASES = {
   "d11": "D11 BUSINESS",
   "d11 business": "D11 BUSINESS",
   "d12": "D12 Medical",
   "d12 medical": "D12 Medical",
   "ww1": "WW1",
   "waterway 1": "WW1",
   "ww2": "WW2",
   "waterway 2": "WW2",
   "tijan": "TIJAN",
   "midst": "MIDST",
   "stage x": "STAGE X",
   "stagex": "STAGE X",
   "resale": "RESALE",
   "metro": "Metro Degla",
   "metro degla": "Metro Degla",
}

COMPANY_INFO = """
معمار دجلة للتطوير العقاري - MEMAAR DEGLA DEVELOPMENT
تأسست: 2019 في العاشر من رمضان
فريق: أكثر من 65 متخصص - تمويل ذاتي بالكامل
الموقع: memaardegla.com | 15409
المؤسسون: أ/ أحمد عبد العزيز | م/ معاذ باشا | أ/ محمد خليل
"""

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)
av_sh = gc.open_by_key(AV_SHEET_ID)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

user_context = {}
chat_history = {}

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
   import re
   patterns = [r'(\d+)\s*متر', r'(\d+)\s*م', r'(\d+)\s*sqm', r'مساحت[هة]\s*(\d+)', r'(\d+)\s*m']
   for pattern in patterns:
       match = re.search(pattern, text.lower())
       if match:
           return int(match.group(1))
   return None

def get_all_units(project_filter=None, status_filter=None, area_filter=None):
   try:
       all_units = []
       for ws in av_sh.worksheets():
           if project_filter and project_filter.lower() not in ws.title.lower():
               continue
           data = ws.get_all_values()
           for row in data:
               if len(row) < 8:
                   continue
               row_status = ""
               status_col = -1
               for i, cell in enumerate(row):
                   if cell.strip().lower() in ["available", "reserved", "hold"]:
                       row_status = cell.strip().lower()
                       status_col = i
                       break
               if not row_status:
                   continue
               if status_filter and row_status != status_filter.lower():
                   continue
               unit = row[2] if len(row) > 2 else ""
               area = row[3] if len(row) > 3 else ""
               total = row[5] if len(row) > 5 else ""
               down = row[8] if len(row) > 8 else ""
               if not unit:
                   continue
               if area_filter:
                   try:
                       area_val = float(str(area).replace(",", "").strip())
                       if abs(area_val - area_filter) > 2:
                           continue
                   except:
                       continue
               all_units.append({
                   "sheet": ws.title,
                   "unit": unit,
                   "area": area,
                   "total": total,
                   "down": down,
                   "status": row_status
               })
       return all_units
   except:
       return []

def get_project_status(project_filter=None):
   try:
       results = {}
       for ws in av_sh.worksheets():
           if project_filter and project_filter.lower() not in ws.title.lower():
               continue
           data = ws.get_all_values()
           counts = {"available": 0, "reserved": 0, "hold": 0}
           for row in data:
               for cell in row:
                   cell_lower = cell.strip().lower()
                   if cell_lower in counts:
                       counts[cell_lower] += 1
           total = sum(counts.values())
           if total > 0:
               results[ws.title] = counts
       return results
   except:
       return {}

def format_status(results):
   if not results:
       return "لا توجد بيانات."
   text = ""
   for project, counts in results.items():
       total = sum(counts.values())
       text += f"📊 *{project}*\n"
       text += f"✅ متاح: {counts['available']}\n"
       text += f"🔴 محجوز: {counts['reserved']}\n"
       text += f"🔵 Hold: {counts['hold']}\n"
       text += f"📦 الإجمالي: {total}\n\n"
   return text if text else "لا توجد بيانات."

def format_units(units, title=""):
   if not units:
       return "لا توجد وحدات بهذه المواصفات."
   result = f"{title}\n\n" if title else ""
   current_sheet = ""
   for u in units:
       if u["sheet"] != current_sheet:
           current_sheet = u["sheet"]
           result += f"*{current_sheet}:*\n"
       result += f"• {u['unit']} | {u['area']}م² | {u['total']} جنيه | مقدم {u['down']}\n"
   return result

def get_or_create_sheet(project):
   try:
       ws = sh.worksheet(project)
   except:
       ws = sh.add_worksheet(title=project, rows=1000, cols=10)
       ws.append_row(["سؤال", "جواب", "اسم الوحدة", "عدد الامتار", "سعر المتر"])
   return ws

def write_to_sheet(project, field, value):
   try:
       ws = get_or_create_sheet(project)
       data = ws.get_all_values()
       for i, row in enumerate(data):
           if row and row[0].strip() == field.strip():
               ws.update_cell(i+1, 2, value)
               return True
       ws.append_row([field, value])
       return True
   except:
       return False

def get_project_data(project_name):
   try:
       ws = sh.worksheet(project_name)
       data = ws.get_all_values()
       result = ""
       for row in data[1:]:
           if len(row) >= 2 and row[0] and row[1]:
               result += f"{row[0]}: {row[1]}\n"
       return result
   except:
       return ""

def save_sale(project, unit, price, client_name):
   try:
       try:
           ws = sh.worksheet("المبيعات")
       except:
           ws = sh.add_worksheet(title="المبيعات", rows=1000, cols=10)
           ws.append_row(["المشروع", "الوحدة", "السعر", "اسم العميل", "التاريخ"])
       from datetime import datetime
       date = datetime.now().strftime("%Y-%m-%d %H:%M")
       ws.append_row([project, unit, price, client_name, date])
       return True
   except:
       return False

def get_sales_data():
   try:
       ws = sh.worksheet("المبيعات")
       data = ws.get_all_values()
       if len(data) <= 1:
           return "لا توجد مبيعات مسجلة حتى الآن."
       result = ""
       for row in data[1:]:
           if len(row) >= 4:
               result += f"• {row[0]} - {row[1]} - {row[2]} - {row[3]} - {row[4]}\n"
       return result
   except:
       return "لا توجد مبيعات مسجلة."

def get_style_buttons():
   keyboard = [
       [
           InlineKeyboardButton("😣 Pain Point", callback_data="style_pain"),
           InlineKeyboardButton("📊 المقارنة", callback_data="style_compare")
       ],
       [
           InlineKeyboardButton("⏰ FOMO", callback_data="style_fomo"),
           InlineKeyboardButton("💰 ROI والأرقام", callback_data="style_roi")
       ],
       [
           InlineKeyboardButton("📖 القصة", callback_data="style_story"),
           InlineKeyboardButton("⭐ Social Proof", callback_data="style_social")
       ],
       [
           InlineKeyboardButton("💎 Exclusivity", callback_data="style_exclusive")
       ]
   ]
   return InlineKeyboardMarkup(keyboard)

STYLES = {
   "style_pain": ("Pain Point", "ابدأ بمشكلة العميل وألمه"),
   "style_compare": ("المقارنة", "قارن بين الإيجار والشراء بالأرقام"),
   "style_fomo": ("FOMO", "ضغط الوقت والندرة بأسلوب راقي"),
   "style_roi": ("ROI والأرقام", "احسبله العائد بالأرقام"),
   "style_story": ("القصة", "قصة عميل حقيقي نجح"),
   "style_social": ("Social Proof", "أرقام مبيعات وشهادات"),
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
       "مرحباً بك في معمار دجلة!\n\n"
       "يمكنني مساعدتك في:\n"
       "• الاستفسار عن الوحدات المتاحة\n"
       "• فلترة الوحدات بالمساحة والحالة\n"
       "• إنشاء إعلانات وسكريبتات\n"
       "• تسجيل المبيعات\n\n"
       "كيف يمكنني مساعدتك؟"
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
   project_data = get_project_data(project) if project else ""

   system = f"""أنت خبير تسويق عقاري في شركة معمار دجلة.
{COMPANY_INFO}
معلومات المشروع: {project_data}
تفاصيل العميل: {request}
الأسلوب: {style_name} - {style_instruction}
اكتب سكريبت واتساب بأسلوب مصري راقٍ. افتتاحية جذابة + معلومات سلسة + نهاية للتواصل.
لا تذكر أي اسم غير معمار دجلة."""

   response = client.messages.create(
       model="claude-haiku-4-5-20251001",
       max_tokens=800,
       system=system,
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
           user_context[user_id]["waiting_password"] = False
           user_context[user_id]["authenticated"] = True
           sales = get_sales_data()
           await update.message.reply_text(f"سجل المبيعات:\n\n{sales}")
       else:
           await update.message.reply_text("كلمة المرور غير صحيحة.")
       return

   if "مبيعات" in msg_lower or "بايعين" in msg_lower or "احنا بعنا" in msg_lower:
       if user_context.get(user_id, {}).get("authenticated"):
           sales = get_sales_data()
           await update.message.reply_text(f"سجل المبيعات:\n\n{sales}")
       else:
           user_context[user_id] = {"waiting_password": True}
           await update.message.reply_text("من فضلك أدخل كلمة المرور:")
       return

   if "بيعة" in msg_lower or "بعنا" in msg_lower or "اتباع" in msg_lower:
       system = """استخرج معلومات البيعة وأرجع JSON فقط:
{"action":"sale","project":"اسم","unit":"وحدة","price":"سعر","client":"عميل"}"""
       response = client.messages.create(
           model="claude-haiku-4-5-20251001",
           max_tokens=200,
           system=system,
           messages=[{"role": "user", "content": user_message}]
       )
       reply = response.content[0].text.strip()
       try:
           data = json.loads(reply[reply.find("{"):reply.rfind("}")+1])
           if data.get("action") == "sale":
               save_sale(data["project"], data["unit"], data["price"], data["client"])
               await update.message.reply_text(
                   f"✅ تم تسجيل البيعة\n"
                   f"المشروع: {data['project']} | الوحدة: {data['unit']}\n"
                   f"السعر: {data['price']} | العميل: {data['client']}"
               )
           return
       except:
           pass

   detected_project = detect_project(user_message)
   area_filter = extract_area(user_message)

   keywords_all = ["كل المشاريع", "كل حاجه", "الكل", "جميع", "overview", "كل الاتاحه"]
   keywords_status = ["كام وحدة", "وحدات", "متاح", "reserved", "hold", "الوضع", "status", "احصائيه", "احصائية", "ايه الوضع", "كام", "إتاحة", "اتاحة", "اتاحه"]
   keywords_available = ["متاح", "available", "فاضي", "المتاح"]

   if any(k in msg_lower for k in keywords_all) and not detected_project:
       if area_filter:
           units = get_all_units(area_filter=area_filter)
           text = format_units(units, f"الوحدات ذات المساحة {area_filter}م² في جميع المشاريع:")
           await update.message.reply_text(text, parse_mode="Markdown")
       else:
           results = get_project_status()
           text = format_status(results)
           await update.message.reply_text(f"📊 *ملخص جميع المشاريع*\n\n{text}", parse_mode="Markdown")
       return

   if any(k in msg_lower for k in keywords_status):
       status_filter = None
       if any(k in msg_lower for k in keywords_available):
           status_filter = "available"
       elif "reserved" in msg_lower or "محجوز" in msg_lower:
           status_filter = "reserved"
       elif "hold" in msg_lower:
           status_filter = "hold"

       if area_filter or status_filter:
           units = get_all_units(
               project_filter=detected_project,
               status_filter=status_filter,
               area_filter=area_filter
           )
           title = f"الوحدات"
           if status_filter:
               title += f" {status_filter}"
           if area_filter:
               title += f" ({area_filter}م²)"
           if detected_project:
               title += f" في {detected_project}"
           text = format_units(units, title + ":")
           await update.message.reply_text(text, parse_mode="Markdown")
       else:
           results = get_project_status(detected_project)
           text = format_status(results)
           header = f"📊 *{detected_project}*\n\n" if detected_project else "📊 *ملخص المشاريع*\n\n"
           await update.message.reply_text(header + text, parse_mode="Markdown")
       return

   project_data = get_project_data(detected_project) if detected_project else ""

   if "سكريبت" in msg_lower:
       user_context[user_id] = {"project": detected_project or "", "request": user_message}
       await update.message.reply_text(
           f"سكريبت {detected_project or ''} - اختر الأسلوب:",
           reply_markup=get_style_buttons()
       )
       return

   if "اعلان" in msg_lower or "إعلان" in msg_lower:
       system = f"""أنت خبير تسويق عقاري في معمار دجلة.
{COMPANY_INFO}
معلومات المشروع: {project_data}
اكتب 3 صيغ إعلانية بأسلوب مصري راقٍ. افتتاحية + معلومات + call to action.
لا تذكر أي اسم غير معمار دجلة."""
       response = client.messages.create(
           model="claude-haiku-4-5-20251001",
           max_tokens=1200,
           system=system,
           messages=[{"role": "user", "content": user_message}]
       )
       await update.message.reply_text(response.content[0].text)
       return

   add_to_history(user_id, "user", user_message)

   system = f"""أنت مساعد فريق مبيعات شركة معمار دجلة.
تتحدث بأسلوب مصري راقٍ وطبيعي. اسم الشركة دائماً "معمار دجلة" فقط.
{COMPANY_INFO}
المشاريع: {", ".join(PROJECTS)}
{f"معلومات {detected_project}:{chr(10)}{project_data}" if project_data else ""}
إذا أراد إضافة معلومة - أرجع JSON فقط:
{{"action":"save","project":"اسم","fields":[{{"field":"حقل","value":"قيمة"}}]}}
إذا سأل - أجب بشكل طبيعي ومختصر."""

   history = get_history(user_id)
   response = client.messages.create(
       model="claude-haiku-4-5-20251001",
       max_tokens=800,
       system=system,
       messages=history
   )
   reply = response.content[0].text.strip()
   add_to_history(user_id, "assistant", reply)

   if '"action"' in reply and '"save"' in reply:
       try:
           data = json.loads(reply[reply.find("{"):reply.rfind("}")+1])
           if data.get("action") == "save":
               project = data.get("project")
               for f in data.get("fields", []):
                   write_to_sheet(project, f["field"], f["value"])
               await update.message.reply_text(f"✅ تم حفظ المعلومات في {project}")
           return
       except:
           pass

   await update.message.reply_text(reply)

def main():
   app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
   app.add_handler(CommandHandler("start", start))
   app.add_handler(CallbackQueryHandler(handle_callback))
   app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
   app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
   main()

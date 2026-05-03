import os
import json
import anthropic
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
AV_SHEET_ID = "1f-1lkgr7nGiQofoREnhfbszjaJFu17OtZaMJ09_sLWw"
PROJECTS = ["D11", "D12", "Metro Degla", "Medist", "Tigan", "Waterway 1", "Waterway 2", "Stage X"]
SECRET_PASSWORD = os.environ.get("SECRET_PASSWORD", "Adel2026")

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sh = gc.open_by_key(SHEET_ID)
av_sh = gc.open_by_key(AV_SHEET_ID)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

user_context = {}

def get_availability_data(query=""):
   try:
       all_data = []
       for ws in av_sh.worksheets():
           try:
               data = ws.get_all_values()
               if len(data) < 3:
                   continue
               headers = data[2]
               for row in data[3:]:
                   if len(row) >= 8 and row[2]:
                       unit = {
                           "sheet": ws.title,
                           "unit": row[2] if len(row) > 2 else "",
                           "area": row[3] if len(row) > 3 else "",
                           "price": row[4] if len(row) > 4 else "",
                           "total": row[5] if len(row) > 5 else "",
                           "project": row[6] if len(row) > 6 else "",
                           "status": row[7] if len(row) > 7 else "",
                           "down_payment": row[8] if len(row) > 8 else "",
                           "instalments": row[9] if len(row) > 9 else "",
                           "cash_discount": row[10] if len(row) > 10 else ""
                       }
                       all_data.append(unit)
           except:
               continue
       return all_data
   except:
       return []

def search_units(query, status_filter=None, project_filter=None):
   all_data = get_availability_data()
   results = []
   for unit in all_data:
       if status_filter and unit["status"].lower() != status_filter.lower():
           continue
       if project_filter and project_filter.lower() not in unit["project"].lower() and project_filter.lower() not in unit["sheet"].lower():
           continue
       if query:
           query_lower = query.lower()
           if any(query_lower in str(v).lower() for v in unit.values()):
               results.append(unit)
       else:
           results.append(unit)
   return results[:20]

def format_units(units):
   if not units:
       return "مفيش وحدات بالشروط دي"
   result = ""
   for u in units:
       result += f"• {u['unit']} | {u['area']}م | {u['total']} جنيه | {u['status']} | مقدم {u['down_payment']}\n"
   return result

def get_or_create_sheet(project):
   try:
       ws = sh.worksheet(project)
   except:
       ws = sh.add_worksheet(title=project, rows=1000, cols=10)
       ws.append_row(["سؤال", "جواب", "اسم الوحدة", "عدد الامتار", "سعر المتر"])
   return ws

def write_unit_to_sheet(project, unit_name, meters, price_per_meter):
   try:
       ws = get_or_create_sheet(project)
       data = ws.get_all_values()
       for i, row in enumerate(data):
           if len(row) >= 3 and row[2].strip() == unit_name.strip():
               ws.update_cell(i+1, 3, unit_name)
               ws.update_cell(i+1, 4, meters)
               ws.update_cell(i+1, 5, price_per_meter)
               return True
       ws.insert_row(["", "", unit_name, meters, price_per_meter], 2)
       return True
   except:
       return False

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
       units = []
       for row in data[1:]:
           if len(row) >= 2 and row[0] and row[1]:
               result += f"{row[0]}: {row[1]}\n"
           if len(row) >= 5 and row[2]:
               units.append(f"وحدة {row[2]}: {row[3]} متر - {row[4]} جنيه للمتر")
       if units:
           result += "\nالوحدات:\n" + "\n".join(units)
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
           return "مفيش مبيعات مسجلة لحد دلوقتي"
       result = ""
       for row in data[1:]:
           if len(row) >= 4:
               result += f"• {row[0]} - {row[1]} - {row[2]} - {row[3]} - {row[4]}\n"
       return result
   except:
       return "مفيش مبيعات مسجلة"

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
   "style_pain": ("Pain Point", "ابدأ بمشكلة العميل وألمه، وريه إن المشروع ده هو الحل"),
   "style_compare": ("المقارنة", "قارن بين الإيجار والشراء بالأرقام الحقيقية"),
   "style_fomo": ("FOMO", "ضغط الوقت والندرة بأسلوب راقي"),
   "style_roi": ("ROI والأرقام", "احسبله العائد والأرقام بشكل واضح"),
   "style_story": ("القصة", "قصة عميل حقيقي نجح واستفاد"),
   "style_social": ("Social Proof", "أرقام مبيعات وشهادات موثوقة"),
   "style_exclusive": ("Exclusivity", "الحصرية والندرة وإن مش للكل")
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   await update.message.reply_text("اهلا يسطا! انا مساعد السيلز، اسألني عن اي مشروع او قولي اكتب اعلان او سكريبت واسم المشروع")

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

   system = f"""انت كونتنت كرييتور متخصص في العقارات المصرية.
اكتب سكريبت واتساب احترافي وشيك بالعربية البسيطة الطبيعية.
معلومات المشروع: {project_data}
تفاصيل العميل: {request}
الاسلوب: {style_name} - {style_instruction}
قواعد: Hook يخطف في السطر الاول، معلومات طبيعية مش ممله، نهاية تخليه ياخد اكشن، شيك ومحترم، مناسب لواتساب."""

   response = client.messages.create(
       model="claude-haiku-4-5-20251001",
       max_tokens=800,
       system=system,
       messages=[{"role": "user", "content": f"اكتب سكريبت {style_name} لمشروع {project}"}]
   )
   await query.edit_message_text(f"*سكريبت {style_name} - {project}*\n\n{response.content[0].text}", parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
   user_message = update.message.text.strip()
   user_id = update.message.from_user.id

   if user_context.get(user_id, {}).get("waiting_password"):
       if user_message == SECRET_PASSWORD:
           user_context[user_id]["waiting_password"] = False
           user_context[user_id]["authenticated"] = True
           sales = get_sales_data()
           await update.message.reply_text(f"المبيعات:\n\n{sales}")
       else:
           await update.message.reply_text("كلمة السر غلط")
       return

   if "مبيعات" in user_message or "بايعين" in user_message or "احنا بعنا" in user_message:
       if user_context.get(user_id, {}).get("authenticated"):
           sales = get_sales_data()
           await update.message.reply_text(f"المبيعات:\n\n{sales}")
       else:
           user_context[user_id] = {"waiting_password": True}
           await update.message.reply_text("اكتب كلمة السر:")
       return

   if "بيعة" in user_message or "بعنا" in user_message or "اتباع" in user_message:
       system = f"""استخرج من الرسالة دي معلومات البيعة وارجع JSON فقط:
{{"action":"sale","project":"اسم المشروع","unit":"الوحدة","price":"السعر","client":"اسم العميل"}}"""
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
               await update.message.reply_text(f"تم تسجيل البيعة ✅\n{data['project']} - {data['unit']} - {data['price']} - {data['client']}")
           return
       except:
           pass

   keywords_av = ["متاح", "available", "فاضي", "فيه وحدة", "كام وحدة", "وحدات متاحة", "ايه المتاح"]
   if any(k in user_message.lower() for k in keywords_av):
       project_filter = None
       for p in ["WW1", "WW2", "D11", "D12", "TIJAN", "MIDST", "STAGE X"]:
           if p.lower() in user_message.lower():
               project_filter = p
               break
       units = search_units("", status_filter="available", project_filter=project_filter)
       formatted = format_units(units)
       await update.message.reply_text(f"الوحدات المتاحة:\n\n{formatted}")
       return

   project_data = ""
   detected_project = ""
   for p in PROJECTS:
       if p.lower() in user_message.lower():
           project_data = get_project_data(p)
           detected_project = p
           break

   if "وحدة" in user_message and detected_project:
       system = f"""استخرج من الرسالة دي معلومات الوحدة وارجع JSON فقط:
{{"action":"unit","project":"اسم المشروع","unit_name":"اسم الوحدة","meters":"المساحة بالمتر","price_per_meter":"سعر المتر"}}"""
       response = client.messages.create(
           model="claude-haiku-4-5-20251001",
           max_tokens=200,
           system=system,
           messages=[{"role": "user", "content": user_message}]
       )
       reply = response.content[0].text.strip()
       try:
           data = json.loads(reply[reply.find("{"):reply.rfind("}")+1])
           if data.get("action") == "unit":
               write_unit_to_sheet(data["project"], data["unit_name"], data["meters"], data["price_per_meter"])
               await update.message.reply_text(f"تم اضافة الوحدة ✅\n{data['unit_name']} - {data['meters']} متر - {data['price_per_meter']} للمتر")
           return
       except:
           pass

   if "سكريبت" in user_message:
       user_context[user_id] = {"project": detected_project, "request": user_message}
       await update.message.reply_text(f"تمام! سكريبت {detected_project} - اختار الاسلوب:", reply_markup=get_style_buttons())
       return

   if "اعلان" in user_message or "إعلان" in user_message:
       system = f"""انت كونتنت كرييتور عقاري مصري. اكتب 3 صيغ اعلانية مختلفة شيك بالعامية المصرية.
معلومات المشروع: {project_data}
كل اعلان: hook يخطف + معلومات طبيعية + call to action. احترافي يليق بالعقارات."""
       response = client.messages.create(
           model="claude-haiku-4-5-20251001",
           max_tokens=1200,
           system=system,
           messages=[{"role": "user", "content": user_message}]
       )
       await update.message.reply_text(response.content[0].text)
       return

   units_context = ""
   for p in ["WW1", "WW2", "D11", "D12", "TIJAN", "MIDST", "STAGE X"]:
       if p.lower() in user_message.lower():
           units = search_units("", project_filter=p)
           if units:
               units_context = f"\nالوحدات في {p}:\n" + format_units(units)
           break

   system = f"""انت سيلز عقاري مصري محترف بتكلم زميلك بالعامية المصرية.
المشاريع: {", ".join(PROJECTS)}
{f"معلومات {detected_project}:{chr(10)}{project_data}" if project_data else ""}
{units_context}
لو بيدي معلومة جديدة - رد بـ JSON فقط:
{{"action":"save","project":"اسم","fields":[{{"field":"حقل","value":"قيمة"}}]}}
لو بيسأل - رد طبيعي بالعامية."""

   response = client.messages.create(
       model="claude-haiku-4-5-20251001",
       max_tokens=800,
       system=system,
       messages=[{"role": "user", "content": user_message}]
   )
   reply = response.content[0].text.strip()

   if '"action"' in reply and '"save"' in reply:
       try:
           data = json.loads(reply[reply.find("{"):reply.rfind("}")+1])
           if data.get("action") == "save":
               project = data.get("project")
               for f in data.get("fields", []):
                   write_to_sheet(project, f["field"], f["value"])
               await update.message.reply_text(f"تم حفظ المعلومات في {project} ✅")
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

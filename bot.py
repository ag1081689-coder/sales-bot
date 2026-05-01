import os
import json
import anthropic
import gspread
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# Google Sheets setup
SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"
PROJECTS = ["D11", "D12", "Metro Degla", "Medist", "Tigan", "Waterway 1", "Waterway 2", "Stage X"]

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds_json)
sheet = gc.open_by_key(SHEET_ID)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

def get_project_data(project_name):
    try:
        ws = sheet.worksheet(project_name)
        data = ws.get_all_values()
        result = ""
        for row in data:
            if len(row) >= 2:
                result += f"{row[0]}: {row[1]}\n"
        return result
    except:
        return "مش لاقي المشروع ده"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    projects_list = "\n".join([f"{i+1}. {p}" for i, p in enumerate(PROJECTS)])
    await update.message.reply_text(
        f"أهلاً! أنا مساعد السيلز 🏢\n\nاختار المشروع:\n{projects_list}\n\nاكتب اسم المشروع وسؤالك"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    
    # detect project
    project_data = ""
    detected_project = ""
    for p in PROJECTS:
        if p.lower() in user_message.lower():
            project_data = get_project_data(p)
            detected_project = p
            break
    
    system_prompt = f"""أنت مساعد سيلز محترف متخصص في العقارات.
{f'معلومات مشروع {detected_project}:{chr(10)}{project_data}' if project_data else 'اطلب من السيلز يحدد المشروع الأول.'}
رد بشكل طبيعي ومختصر."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251

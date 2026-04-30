import os
import anthropic
import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SHEET_ID = "1x5CfKVrgXZy1-1yVPoqAwcS0KpxeOyzxfA8shDt2qkw"

def get_sheet_data():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"
    response = requests.get(url)
    lines = response.text.strip().split("\n")
    qa = ""
    for line in lines[1:]:
        parts = line.split('","')
        if len(parts) >= 2:
            question = parts[0].replace('"', '').strip()
            answer = parts[1].replace('"', '').strip()
            qa += f"س: {question}\nج: {answer}\n\n"
    return qa

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    sheet_data = get_sheet_data()
    
    system_prompt = f"""أنت مساعد سيلز محترف متخصص في العقارات.
عندك المعلومات دي عن المشروع:

{sheet_data}

رد على أسئلة السيلز بشكل طبيعي ومختصر بناءً على المعلومات دي.
لو السؤال مش موجود قول: مش عندي معلومة عن ده."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    await update.message.reply_text(response.content[0].text)

def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

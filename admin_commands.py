from aiogram import types
import sqlite3

async def cmd_history(message: types.Message):
    """История рассылок"""
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM mailings ORDER BY sent_date DESC LIMIT 10")
    mailings = cursor.fetchall()
    conn.close()
    
    if not mailings:
        await message.answer("История рассылок пуста.")
        return
    
    text = "📨 <b>Последние 10 рассылок:</b>\n\n"
    for mailing in mailings:
        text += f"📅 {mailing[3]}\n"
        text += f"📊 Отправлено: {mailing[4]} пользователей\n"
        text += f"📝 Текст: {mailing[1][:50]}...\n"
        text += "─" * 30 + "\n"
    
    await message.answer(text, parse_mode=types.ParseMode.HTML)

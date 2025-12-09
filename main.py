import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ParseMode
from aiogram.utils import executor
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

# Настройки
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(','))) if os.getenv("ADMIN_IDS") else []

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# База данных
DB_NAME = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица рассылок
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS mailings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        photo TEXT,
        sent_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sent_count INTEGER DEFAULT 0
    )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# States для FSM
class MailingStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()
    confirmation = State()

# Проверка прав администратора
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    # Сохраняем пользователя в БД
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
        (user_id, username, full_name)
    )
    conn.commit()
    conn.close()
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    if is_admin(user_id):
        keyboard.add("📊 Статистика", "📢 Рассылка")
        await message.answer(
            f"Привет, администратор {full_name}!",
            reply_markup=keyboard
        )
    else:
        keyboard.add("ℹ️ Информация", "🔔 Подписаться")
        await message.answer(
            f"Добро пожаловать, {full_name}!",
            reply_markup=keyboard
        )

# Админка: Статистика
@dp.message_handler(lambda message: message.text == "📊 Статистика" and is_admin(message.from_user.id))
async def cmd_stats(message: types.Message):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Общее количество пользователей
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # Количество новых пользователей за сегодня
    cursor.execute("SELECT COUNT(*) FROM users WHERE date(joined_date) = date('now')")
    new_today = cursor.fetchone()[0]
    
    conn.close()
    
    await message.answer(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"🆕 Новых сегодня: <b>{new_today}</b>",
        parse_mode=ParseMode.HTML
    )

# Админка: Начало рассылки
@dp.message_handler(lambda message: message.text == "📢 Рассылка" and is_admin(message.from_user.id))
async def start_mailing(message: types.Message):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("📝 Текст", "🖼 Текст + фото", "❌ Отмена")
    await message.answer("Выберите тип рассылки:", reply_markup=keyboard)

# Отмена рассылки
@dp.message_handler(lambda message: message.text == "❌ Отмена" and is_admin(message.from_user.id), state="*")
async def cancel_mailing(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Рассылка отменена.", reply_markup=types.ReplyKeyboardRemove())

# Выбор типа рассылки: текст
@dp.message_handler(lambda message: message.text == "📝 Текст" and is_admin(message.from_user.id))
async def mailing_text(message: types.Message):
    await MailingStates.waiting_for_text.set()
    await message.answer("Отправьте текст для рассылки:", reply_markup=types.ReplyKeyboardRemove())

# Получение текста для рассылки
@dp.message_handler(state=MailingStates.waiting_for_text)
async def process_mailing_text(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['text'] = message.text
        data['photo'] = None
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Отправить", callback_data="confirm_send"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="cancel_send")
    )
    
    await message.answer(
        f"<b>Предпросмотр рассылки:</b>\n\n{message.text}\n\n"
        f"Отправить всем пользователям?",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )
    await MailingStates.confirmation.set()

# Выбор типа рассылки: текст + фото
@dp.message_handler(lambda message: message.text == "🖼 Текст + фото" and is_admin(message.from_user.id))
async def mailing_photo(message: types.Message):
    await MailingStates.waiting_for_photo.set()
    await message.answer("Отправьте фото для рассылки:", reply_markup=types.ReplyKeyboardRemove())

# Получение фото
@dp.message_handler(content_types=['photo'], state=MailingStates.waiting_for_photo)
async def process_mailing_photo(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['photo'] = message.photo[-1].file_id
    await MailingStates.waiting_for_text.set()
    await message.answer("Теперь отправьте текст для рассылки:")

# Подтверждение рассылки
@dp.callback_query_handler(lambda c: c.data in ['confirm_send', 'cancel_send'], state=MailingStates.confirmation)
async def process_confirmation(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    
    if callback_query.data == 'cancel_send':
        await state.finish()
        await bot.send_message(callback_query.from_user.id, "Рассылка отменена.")
        return
    
    # Получаем данные из состояния
    async with state.proxy() as data:
        mailing_text = data.get('text', '')
        mailing_photo = data.get('photo')
    
    # Получаем всех пользователей
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    
    # Отправляем рассылку
    sent_count = 0
    errors = 0
    
    await bot.send_message(callback_query.from_user.id, f"Начинаю рассылку для {len(users)} пользователей...")
    
    for user in users:
        try:
            if mailing_photo:
                await bot.send_photo(
                    chat_id=user[0],
                    photo=mailing_photo,
                    caption=mailing_text,
                    parse_mode=ParseMode.HTML
                )
            else:
                await bot.send_message(
                    chat_id=user[0],
                    text=mailing_text,
                    parse_mode=ParseMode.HTML
                )
            sent_count += 1
            await asyncio.sleep(0.05)  # Задержка чтобы не превысить лимиты Telegram
        except Exception as e:
            errors += 1
            logging.error(f"Ошибка отправки пользователю {user[0]}: {e}")
    
    # Сохраняем рассылку в историю
    cursor.execute(
        "INSERT INTO mailings (text, photo, sent_count) VALUES (?, ?, ?)",
        (mailing_text, mailing_photo, sent_count)
    )
    conn.commit()
    conn.close()
    
    await state.finish()
    await bot.send_message(
        callback_query.from_user.id,
        f"✅ Рассылка завершена!\n\n"
        f"✅ Успешно отправлено: {sent_count}\n"
        f"❌ Ошибок: {errors}",
        reply_markup=types.ReplyKeyboardRemove()
    )

# Для обычных пользователей
@dp.message_handler(lambda message: message.text == "ℹ️ Информация")
async def cmd_info(message: types.Message):
    await message.answer("Это информационный бот. Здесь вы будете получать важные уведомления.")

@dp.message_handler(lambda message: message.text == "🔔 Подписаться")
async def cmd_subscribe(message: types.Message):
    await message.answer("Вы успешно подписались на рассылку!")

# Обработка неизвестных команд
@dp.message_handler()
async def unknown_message(message: types.Message):
    if is_admin(message.from_user.id):
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add("📊 Статистика", "📢 Рассылка")
        await message.answer("Используйте кнопки меню:", reply_markup=keyboard)
    else:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add("ℹ️ Информация", "🔔 Подписаться")
        await message.answer("Используйте кнопки меню:", reply_markup=keyboard)

# Запуск бота
if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)

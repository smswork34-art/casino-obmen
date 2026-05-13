import asyncio
import sqlite3
from decimal import Decimal
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

# Конфигурация
BOT_TOKEN = "8714933043:AAHIP0WJk1SycaKYawxIpT555q1cR4yYlkg"
ADMIN_ID = 7518728008

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Временное хранилище для связи файла с пользователем
file_user_map = {}

# Состояния FSM
class PaymentStates(StatesGroup):
    waiting_for_amount = State()

# Инициализация БД
def init_db():
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0.0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    
    # Таблица транзакций
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_name TEXT,
            amount REAL DEFAULT 0.0,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Работа с БД
def add_user(user_id, username, first_name):
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
        (user_id, username, first_name)
    )
    conn.commit()
    conn.close()

def get_balance(user_id):
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0.0

def update_balance(user_id, amount):
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE users SET balance = balance + ? WHERE user_id = ?',
        (amount, user_id)
    )
    conn.commit()
    conn.close()

def add_transaction(user_id, file_name):
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO transactions (user_id, file_name, status, amount) VALUES (?, ?, ?, ?)',
        (user_id, file_name, 'pending', 0.0)
    )
    conn.commit()
    conn.close()

def update_transaction(user_id, status, amount=0.0):
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    cursor.execute(
        '''UPDATE transactions 
           SET status = ?, amount = ? 
           WHERE user_id = ? AND status = 'pending'
           AND id = (SELECT MAX(id) FROM transactions WHERE user_id = ? AND status = 'pending')''',
        (status, amount, user_id, user_id)
    )
    conn.commit()
    conn.close()

# Клавиатуры
def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузить токены", callback_data="upload_tokens")]
    ])

def get_admin_keyboard(file_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Блок", callback_data=f"block_{file_id}")],
        [InlineKeyboardButton(text="💰 Ввести кол-во оплаты", callback_data=f"amount_{file_id}")],
        [InlineKeyboardButton(text="🔄 Слет все сразу", callback_data=f"decline_{file_id}")]
    ])

# Обработчики
@dp.message(Command("start"))
async def start_command(message: types.Message):
    # Сохраняем пользователя в БД
    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я бот для приёмки токенов MAX на RENDER.\n"
        "Нажми кнопку ниже, чтобы загрузить файл с токенами.",
        reply_markup=get_start_keyboard()
    )

@dp.callback_query(F.data == "upload_tokens")
async def upload_tokens(callback: types.CallbackQuery):
    await callback.message.answer("📎 Пожалуйста, загрузите файл токенов в формате .txt")
    await callback.answer()

@dp.message(F.document)
async def handle_document(message: types.Message):
    if not message.document.file_name.endswith('.txt'):
        await message.answer("❌ Пожалуйста, загрузите файл в формате .txt")
        return
    
    # Сохраняем связь файла с пользователем
    file_id = message.document.file_id
    file_user_map[file_id] = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "file_name": message.document.file_name
    }
    
    # Сохраняем пользователя и создаем транзакцию
    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    add_transaction(message.from_user.id, message.document.file_name)
    
    # Пересылаем файл админу
    await bot.send_document(
        ADMIN_ID,
        message.document.file_id,
        caption=f"📄 Файл от @{message.from_user.username or 'нет юзернейма'} (ID: {message.from_user.id})\nИмя: {message.from_user.first_name}",
        reply_markup=get_admin_keyboard(file_id)
    )
    
    await message.answer("✅ Файл загружен, ожидайте пополнение счета")

@dp.callback_query(F.data.startswith("block_"))
async def block_file(callback: types.CallbackQuery):
    file_id = callback.data.replace("block_", "")
    user_data = file_user_map.get(file_id)
    
    if user_data:
        # Обновляем статус транзакции
        update_transaction(user_data["user_id"], "blocked")
        
        # Уведомляем пользователя
        await bot.send_message(user_data["user_id"], "❌ Блок, нет оплаты")
        
        # Обновляем сообщение админу
        await callback.message.edit_caption(
            callback.message.caption + "\n\n❌ ЗАБЛОКИРОВАНО",
            reply_markup=None
        )
    
    await callback.answer("Файл заблокирован")

@dp.callback_query(F.data.startswith("decline_"))
async def decline_file(callback: types.CallbackQuery):
    file_id = callback.data.replace("decline_", "")
    user_data = file_user_map.get(file_id)
    
    if user_data:
        update_transaction(user_data["user_id"], "declined")
        
        await bot.send_message(user_data["user_id"], "🔄 Всё слет, не оплата")
        
        await callback.message.edit_caption(
            callback.message.caption + "\n\n🔄 СЛЕТ",
            reply_markup=None
        )
    
    await callback.answer("Файл отклонён")

@dp.callback_query(F.data.startswith("amount_"))
async def set_amount(callback: types.CallbackQuery, state: FSMContext):
    file_id = callback.data.replace("amount_", "")
    user_data = file_user_map.get(file_id)
    
    if user_data:
        await state.update_data(current_user_id=user_data["user_id"])
        await state.set_state(PaymentStates.waiting_for_amount)
        await callback.message.answer("💰 Введите сумму оплаты в долларах (например 5.50):")
    
    await callback.answer()

@dp.message(PaymentStates.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
        
        data = await state.get_data()
        user_id = data["current_user_id"]
        
        # Обновляем баланс и транзакцию
        update_balance(user_id, amount)
        update_transaction(user_id, "paid", amount)
        
        # Получаем актуальный баланс
        new_balance = get_balance(user_id)
        
        # Уведомляем пользователя
        await bot.send_message(
            user_id,
            f"✅ Ваш баланс пополнен на ${amount:.2f}\n💰 Текущий баланс: ${new_balance:.2f}"
        )
        
        await message.answer(f"✅ Баланс пользователя пополнен на ${amount:.2f}")
        await state.clear()
        
    except (ValueError, Exception) as e:
        await message.answer("❌ Пожалуйста, введите корректную сумму (например 5.50)")
        print(f"Error: {e}")

@dp.message(Command("balance"))
async def check_balance(message: types.Message):
    balance = get_balance(message.from_user.id)
    await message.answer(f"💰 Ваш баланс: ${balance:.2f}")

# Запуск бота
async def main():
    # Инициализируем БД
    init_db()
    print("✅ База данных инициализирована")
    print("🤖 Бот запущен!")
    
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

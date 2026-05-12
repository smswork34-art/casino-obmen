import asyncio
import os
import sqlite3
import json
import uuid
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

BOT_TOKEN = "8783429061:AAHdivmiLwPts6u2cOUSRp_78RGf81PSP1w"
CRYPTO_TOKEN = "575343:AA8lI3rebCZuc9HxysqN073qP3jLgrz2sx8"
WEBAPP_URL = "https://smswork34-art.github.io/p2p/index.html"
CASINO_URL = "https://smswork34-art.github.io/p2p/blackjack.html"
RENDER_URL = "https://lvk-bot.onrender.com"
PORT = int(os.getenv("PORT", 10000))

ADMIN_ID = 7518728008
ADMINS = [7518728008]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT DEFAULT 'pending', created_at TEXT)")
    conn.commit()
    conn.close()

def get_balance(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (id, balance) VALUES (?, 0)", (user_id,))
    c.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
    bal = c.fetchone()[0]
    conn.commit()
    conn.close()
    return bal

def add_balance(user_id, amount):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (id, balance) VALUES (?, 0)", (user_id,))
    c.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def create_invoice(user_id, amount):
    inv_id = str(uuid.uuid4())[:12]
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT INTO invoices (id, user_id, amount, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
              (inv_id, user_id, amount, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return inv_id

def get_invoice(inv_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,))
    inv = c.fetchone()
    conn.close()
    return inv

def mark_paid(inv_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (inv_id,))
    conn.commit()
    conn.close()

@dp.message(Command("start"))
async def start(msg: types.Message):
    bal = get_balance(msg.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Обменник", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="Казино", web_app=WebAppInfo(url=CASINO_URL))],
        [InlineKeyboardButton(text="Пополнить", callback_data="deposit")]
    ])
    await msg.answer(f"Баланс: {bal:.2f} USDT\nВыберите раздел:", reply_markup=kb)

@dp.callback_query(F.data == "deposit")
async def deposit(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer("Введите сумму для пополнения в USDT:")

@dp.message(F.text.regexp(r"^\d+(\.\d+)?$"))
async def deposit_amount(msg: types.Message):
    amount = float(msg.text)
    if amount < 1:
        await msg.answer("Минимальная сумма: 1 USDT")
        return
    inv_id = create_invoice(msg.from_user.id, amount)
    pay_link = f"https://t.me/send?start=IVbVWg5ECEkD"
    await msg.answer(
        f"Счёт создан на {amount} USDT\n"
        f"ID: {inv_id}\n"
        f"Оплатите через @send, баланс зачислится автоматически."
    )

async def handle_crypto_webhook(request):
    data = await request.json()
    inv_id = data.get("payload", "")
    status = data.get("status", "")
    if status == "paid":
        inv = get_invoice(inv_id)
        if inv and inv[3] == "pending":
            mark_paid(inv_id)
            add_balance(inv[1], inv[2])
    return web.Response(text="ok")

@dp.message(Command("balance"))
async def balance_cmd(msg: types.Message):
    bal = get_balance(msg.from_user.id)
    await msg.answer(f"Баланс: {bal:.2f} USDT")

async def on_startup():
    init_db()
    await bot.set_webhook(f"{RENDER_URL}/webhook")

async def main():
    await on_startup()
    app = web.Application()
    app.router.add_post("/crypto-webhook", handle_crypto_webhook)
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())

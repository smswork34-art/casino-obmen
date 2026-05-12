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
import aiohttp

BOT_TOKEN = "8692170657:AAHUQjBWkcCAVvchGaMVyWu8jLVjy6cT-ks"
CRYPTO_TOKEN = "575343:AA8lI3rebCZuc9HxysqN073qP3jLgrz2sx8"
WEBAPP_URL = "https://smswork34-art.github.io/p2p/index.html"
CASINO_URL = "https://smswork34-art.github.io/p2p/blackjack.html"
RENDER_URL = "https://casino-obmen.onrender.com"
PORT = int(os.getenv("PORT", 10000))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, balance REAL DEFAULT 0)")
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

async def create_crypto_invoice(amount, payload):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    data = {"asset": "USDT", "amount": str(amount), "payload": payload}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as resp:
            if resp.status == 200:
                result = await resp.json()
                if result.get("ok"):
                    return result["result"]["pay_url"]
    return None

async def check_crypto_invoice(inv_id):
    url = "https://pay.crypt.bot/api/getInvoices"
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    params = {"invoice_ids": inv_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("ok"):
                    items = data["result"].get("items", [])
                    for item in items:
                        if item.get("status") == "paid":
                            return True
    return False

@dp.message(Command("start"))
async def start(msg: types.Message):
    bal = get_balance(msg.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Обменник", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="Казино", web_app=WebAppInfo(url=CASINO_URL))]
    ])
    await msg.answer(f"Баланс: {bal:.2f} USDT", reply_markup=kb)

@dp.message(Command("balance"))
async def balance_cmd(msg: types.Message):
    bal = get_balance(msg.from_user.id)
    await msg.answer(f"Баланс: {bal:.2f} USDT")

async def handle_balance(request):
    user_id = request.match_info.get("user_id", "0")
    bal = get_balance(int(user_id))
    resp = web.json_response({"balance": bal})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

async def create_crypto_invoice(amount, payload):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    data = {"asset": "USDT", "amount": str(amount), "payload": payload}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data, headers=headers) as resp:
            if resp.status == 200:
                result = await resp.json()
                print("CRYPTO CREATE:", json.dumps(result, indent=2))
                if result.get("ok"):
                    crypto_id = result["result"]["invoice_id"]
                    return {"pay_url": result["result"]["pay_url"], "crypto_id": crypto_id}
    return {}

async def handle_create_invoice(request):
    data = await request.json()
    user_id = int(data.get("user_id", 0))
    amount = float(data.get("amount", 0))
    if amount < 1:
        resp = web.json_response({"error": "Min 1 USDT"}, status=400)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    inv_id = create_invoice(user_id, amount)
    result = await create_crypto_invoice(amount, inv_id)
    pay_url = result.get("pay_url", "")
    crypto_id = result.get("crypto_id", "")
    print(f"INV {inv_id} -> CRYPTO {crypto_id}")
    resp = web.json_response({"pay_url": pay_url, "invoice_id": inv_id, "crypto_id": crypto_id})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

async def handle_check_invoice(request):
    data = await request.json()
    inv_id = data.get("invoice_id", "")
    paid = await check_crypto_invoice(inv_id)
    print(f"CHECK {inv_id}: {paid}")
    if paid:
        inv = get_invoice(inv_id)
        if inv and inv[3] == "pending":
            mark_paid(inv_id)
            add_balance(inv[1], inv[2])
    resp = web.json_response({"paid": paid})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

async def handle_options(request):
    resp = web.Response(text="ok")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

async def on_startup():
    init_db()
    await bot.set_webhook(f"{RENDER_URL}/webhook")

async def main():
    await on_startup()
    app = web.Application()
    app.router.add_get("/balance/{user_id}", handle_balance)
    app.router.add_post("/create-invoice", handle_create_invoice)
    app.router.add_post("/check-invoice", handle_check_invoice)
    app.router.add_route("OPTIONS", "/{path:.*}", handle_options)
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

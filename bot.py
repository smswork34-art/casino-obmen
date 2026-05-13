import json
import sqlite3
import time
import urllib.request
import threading
from datetime import datetime

# Конфигурация
BOT_TOKEN = "8714933043:AAHIP0WJk1SycaKYawxIpT555q1cR4yYlkg"
ADMIN_ID = 7518728008
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Временное хранилище
file_user_map = {}
waiting_for_amount = {}  # {admin_id: user_id}

def init_db():
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0.0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_name TEXT,
            amount REAL DEFAULT 0.0,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
    conn.commit()
    conn.close()

def db_execute(query, params=()):
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    conn.close()
    return cursor

def db_fetchone(query, params=()):
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = cursor.fetchone()
    conn.close()
    return result

# Telegram API функции
def send_message(chat_id, text, reply_markup=None):
    data = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    
    req = urllib.request.Request(
        f"{API_URL}sendMessage",
        data=urllib.parse.urlencode(data).encode('utf-8'),
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    urllib.request.urlopen(req)

def send_document(chat_id, file_id, caption, reply_markup=None):
    data = {
        'chat_id': chat_id,
        'document': file_id,
        'caption': caption
    }
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    
    req = urllib.request.Request(
        f"{API_URL}sendDocument",
        data=urllib.parse.urlencode(data).encode('utf-8'),
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    urllib.request.urlopen(req)

def edit_message_caption(chat_id, message_id, caption, reply_markup=None):
    data = {
        'chat_id': chat_id,
        'message_id': message_id,
        'caption': caption
    }
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    
    req = urllib.request.Request(
        f"{API_URL}editMessageCaption",
        data=urllib.parse.urlencode(data).encode('utf-8'),
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    urllib.request.urlopen(req)

def answer_callback(callback_id, text=""):
    data = {
        'callback_query_id': callback_id,
        'text': text
    }
    req = urllib.request.Request(
        f"{API_URL}answerCallbackQuery",
        data=urllib.parse.urlencode(data).encode('utf-8'),
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    urllib.request.urlopen(req)

# Клавиатуры
def get_start_keyboard():
    return {
        'inline_keyboard': [[
            {'text': '📤 Загрузить токены', 'callback_data': 'upload_tokens'}
        ]]
    }

def get_admin_keyboard(file_id):
    return {
        'inline_keyboard': [
            [{'text': '❌ Блок', 'callback_data': f'block_{file_id}'}],
            [{'text': '💰 Ввести кол-во оплаты', 'callback_data': f'amount_{file_id}'}],
            [{'text': '🔄 Слет все сразу', 'callback_data': f'decline_{file_id}'}]
        ]
    }

# Обработка обновлений
def process_update(update):
    try:
        # Обработка сообщений
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            
            # Команда /start
            if 'text' in message and message['text'] == '/start':
                user = message['from']
                db_execute(
                    'INSERT OR IGNORE INTO users (user_id, username, first_name, balance) VALUES (?, ?, ?, ?)',
                    (user['id'], user.get('username'), user.get('first_name'), 0.0)
                )
                
                send_message(
                    chat_id,
                    f"👋 Привет, {user.get('first_name', 'пользователь')}!\n\n"
                    "Я бот для приёмки токенов MAX на RENDER.\n"
                    "Нажми кнопку ниже, чтобы загрузить файл с токенами.",
                    get_start_keyboard()
                )
            
            # Команда /balance
            elif 'text' in message and message['text'] == '/balance':
                result = db_fetchone('SELECT balance FROM users WHERE user_id = ?', (chat_id,))
                balance = result[0] if result else 0.0
                send_message(chat_id, f"💰 Ваш баланс: ${balance:.2f}")
            
            # Обработка документа
            elif 'document' in message:
                doc = message['document']
                
                if not doc.get('file_name', '').endswith('.txt'):
                    send_message(chat_id, "❌ Пожалуйста, загрузите файл в формате .txt")
                    return
                
                user = message['from']
                file_id = doc['file_id']
                
                # Сохраняем связь
                file_user_map[file_id] = {
                    "user_id": user['id'],
                    "username": user.get('username'),
                    "first_name": user.get('first_name'),
                    "file_name": doc.get('file_name')
                }
                
                # Сохраняем в БД
                db_execute(
                    'INSERT OR IGNORE INTO users (user_id, username, first_name, balance) VALUES (?, ?, ?, ?)',
                    (user['id'], user.get('username'), user.get('first_name'), 0.0)
                )
                db_execute(
                    'INSERT INTO transactions (user_id, file_name, status, amount) VALUES (?, ?, ?, ?)',
                    (user['id'], doc.get('file_name'), 'pending', 0.0)
                )
                
                # Отправляем админу
                username = user.get('username', 'нет юзернейма')
                caption = f"📄 Файл от @{username} (ID: {user['id']})\nИмя: {user.get('first_name')}"
                send_document(ADMIN_ID, file_id, caption, get_admin_keyboard(file_id))
                
                send_message(chat_id, "✅ Файл загружен, ожидайте пополнение счета")
            
            # Обработка ввода суммы админом
            elif 'text' in message and chat_id == ADMIN_ID and chat_id in waiting_for_amount:
                try:
                    amount = float(message['text'].replace(',', '.'))
                    if amount <= 0:
                        raise ValueError
                    
                    user_id = waiting_for_amount.pop(chat_id)
                    
                    # Обновляем баланс
                    db_execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
                    
                    # Обновляем транзакцию
                    db_execute(
                        '''UPDATE transactions 
                           SET status = 'paid', amount = ? 
                           WHERE user_id = ? AND status = 'pending'
                           AND id = (SELECT MAX(id) FROM transactions WHERE user_id = ? AND status = 'pending')''',
                        (amount, user_id, user_id)
                    )
                    
                    # Получаем новый баланс
                    result = db_fetchone('SELECT balance FROM users WHERE user_id = ?', (user_id,))
                    new_balance = result[0] if result else amount
                    
                    # Уведомляем пользователя
                    send_message(user_id, f"✅ Ваш баланс пополнен на ${amount:.2f}\n💰 Текущий баланс: ${new_balance:.2f}")
                    send_message(chat_id, f"✅ Баланс пользователя пополнен на ${amount:.2f}")
                    
                except (ValueError, Exception) as e:
                    send_message(chat_id, "❌ Пожалуйста, введите корректную сумму (например 5.50)")
        
        # Обработка callback'ов (кнопки)
        elif 'callback_query' in update:
            callback = update['callback_query']
            data = callback['data']
            msg = callback['message']
            
            # Блок
            if data.startswith('block_'):
                file_id = data.replace('block_', '')
                user_data = file_user_map.get(file_id)
                
                if user_data:
                    user_id = user_data['user_id']
                    db_execute(
                        '''UPDATE transactions 
                           SET status = 'blocked' 
                           WHERE user_id = ? AND status = 'pending'
                           AND id = (SELECT MAX(id) FROM transactions WHERE user_id = ? AND status = 'pending')''',
                        (user_id, user_id)
                    )
                    
                    send_message(user_id, "❌ Блок, нет оплаты")
                    
                    edit_message_caption(
                        msg['chat']['id'],
                        msg['message_id'],
                        msg.get('caption', '') + "\n\n❌ ЗАБЛОКИРОВАНО"
                    )
                
                answer_callback(callback['id'], "Файл заблокирован")
            
            # Слет
            elif data.startswith('decline_'):
                file_id = data.replace('decline_', '')
                user_data = file_user_map.get(file_id)
                
                if user_data:
                    user_id = user_data['user_id']
                    db_execute(
                        '''UPDATE transactions 
                           SET status = 'declined' 
                           WHERE user_id = ? AND status = 'pending'
                           AND id = (SELECT MAX(id) FROM transactions WHERE user_id = ? AND status = 'pending')''',
                        (user_id, user_id)
                    )
                    
                    send_message(user_id, "🔄 Всё слет, не оплата")
                    
                    edit_message_caption(
                        msg['chat']['id'],
                        msg['message_id'],
                        msg.get('caption', '') + "\n\n🔄 СЛЕТ"
                    )
                
                answer_callback(callback['id'], "Файл отклонён")
            
            # Ввод суммы
            elif data.startswith('amount_'):
                file_id = data.replace('amount_', '')
                user_data = file_user_map.get(file_id)
                
                if user_data:
                    waiting_for_amount[ADMIN_ID] = user_data['user_id']
                    send_message(ADMIN_ID, "💰 Введите сумму оплаты в долларах (например 5.50):")
                
                answer_callback(callback['id'])
            
            # Загрузить токены
            elif data == 'upload_tokens':
                send_message(msg['chat']['id'], "📎 Пожалуйста, загрузите файл токенов в формате .txt")
                answer_callback(callback['id'], "")
                
    except Exception as e:
        print(f"Error processing update: {e}")

# Основной цикл
def main():
    init_db()
    print("✅ База данных инициализирована")
    print("🤖 Бот запущен!")
    
    offset = 0
    
    while True:
        try:
            # Получаем обновления
            req = urllib.request.Request(f"{API_URL}getUpdates?offset={offset}&timeout=30")
            response = urllib.request.urlopen(req)
            data = json.loads(response.read().decode('utf-8'))
            
            if data['ok']:
                for update in data['result']:
                    process_update(update)
                    offset = update['update_id'] + 1
            
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()

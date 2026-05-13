import json
import sqlite3
import time
import urllib.request
import urllib.parse
import sys
from datetime import datetime

# Конфигурация
BOT_TOKEN = "8714933043:AAHIP0WJk1SycaKYawxIpT555q1cR4yYlkg"
ADMIN_ID = 7518728008
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Временное хранилище
file_user_map = {}
waiting_for_amount = {}

def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)

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
    log("✅ База данных инициализирована")

def db_execute(query, params=()):
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    conn.close()

def db_fetchone(query, params=()):
    conn = sqlite3.connect('tokens_bot.db')
    cursor = conn.cursor()
    cursor.execute(query, params)
    result = cursor.fetchone()
    conn.close()
    return result

def api_call(method, params):
    """Общая функция для вызовов Telegram API"""
    try:
        url = f"{API_URL}{method}"
        
        if 'document' in params and not params['document'].startswith('http'):
            # Если это file_id, отправляем как form-data
            import io
            boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
            
            body = io.BytesIO()
            
            for key, value in params.items():
                body.write(f'--{boundary}\r\n'.encode())
                body.write(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                body.write(f'{value}\r\n'.encode())
            
            body.write(f'--{boundary}--\r\n'.encode())
            
            req = urllib.request.Request(
                url,
                data=body.getvalue(),
                headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
            )
        else:
            # Обычный POST запрос
            data = urllib.parse.urlencode(params).encode('utf-8')
            req = urllib.request.Request(
                url,
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
        
        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read().decode('utf-8'))
        
        if not result.get('ok'):
            log(f"❌ API Error: {result}")
        
        return result
        
    except Exception as e:
        log(f"❌ API call error for {method}: {str(e)}")
        return None

def send_message(chat_id, text, reply_markup=None):
    params = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        params['reply_markup'] = json.dumps(reply_markup)
    
    result = api_call('sendMessage', params)
    if result:
        log(f"📤 Сообщение отправлено пользователю {chat_id}")
    return result

def forward_document(chat_id, from_chat_id, message_id):
    """Пересылаем документ вместо отправки по file_id"""
    params = {
        'chat_id': chat_id,
        'from_chat_id': from_chat_id,
        'message_id': message_id
    }
    result = api_call('forwardMessage', params)
    if result:
        log(f"📎 Документ переслан админу {chat_id}")
    return result

def send_document(chat_id, file_id, caption, reply_markup=None):
    params = {
        'chat_id': chat_id,
        'document': file_id,
        'caption': caption
    }
    if reply_markup:
        params['reply_markup'] = json.dumps(reply_markup)
    
    log(f"📎 Пытаюсь отправить документ {file_id} пользователю {chat_id}")
    result = api_call('sendDocument', params)
    if result:
        log(f"✅ Документ отправлен")
    return result

def edit_message_caption(chat_id, message_id, caption, reply_markup=None):
    params = {
        'chat_id': chat_id,
        'message_id': message_id,
        'caption': caption
    }
    if reply_markup:
        params['reply_markup'] = json.dumps(reply_markup)
    
    api_call('editMessageCaption', params)

def answer_callback(callback_id, text=""):
    params = {
        'callback_query_id': callback_id,
        'text': text
    }
    api_call('answerCallbackQuery', params)

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

def process_update(update):
    try:
        log(f"📨 Получен update: {json.dumps(update, ensure_ascii=False)[:200]}...")
        
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            
            # /start
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
            
            # /balance
            elif 'text' in message and message['text'] == '/balance':
                result = db_fetchone('SELECT balance FROM users WHERE user_id = ?', (chat_id,))
                balance = result[0] if result else 0.0
                send_message(chat_id, f"💰 Ваш баланс: ${balance:.2f}")
            
            # Документ
            elif 'document' in message:
                doc = message['document']
                log(f"📄 Получен документ: {doc.get('file_name')} от пользователя {chat_id}")
                
                if not doc.get('file_name', '').endswith('.txt'):
                    send_message(chat_id, "❌ Пожалуйста, загрузите файл в формате .txt")
                    return
                
                user = message['from']
                file_id = doc['file_id']
                message_id = message['message_id']
                
                log(f"📎 File ID: {file_id}, Message ID: {message_id}")
                
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
                
                # Пробуем отправить документ админу несколькими способами
                username = user.get('username', 'нет юзернейма')
                caption = f"📄 Файл от @{username} (ID: {user['id']})\nИмя: {user.get('first_name')}"
                
                log(f"🔄 Отправляю документ админу {ADMIN_ID}...")
                
                # Способ 1: Отправка по file_id
                result = send_document(ADMIN_ID, file_id, caption, get_admin_keyboard(file_id))
                
                # Если не получилось, пробуем переслать
                if not result:
                    log("⚠️ Не удалось отправить по file_id, пробую переслать...")
                    result = forward_document(ADMIN_ID, chat_id, message_id)
                    
                    if result:
                        # Добавляем кнопки к пересланному сообщению
                        new_message_id = result['result']['message_id']
                        edit_message_caption(
                            ADMIN_ID, 
                            new_message_id, 
                            caption, 
                            get_admin_keyboard(file_id)
                        )
                        log("✅ Документ переслан с кнопками")
                    else:
                        log("❌ Не удалось отправить документ совсем")
                        send_message(ADMIN_ID, f"⚠️ Пользователь {username} отправил файл, но не удалось его переслать. File ID: {file_id}")
                
                # Сообщаем пользователю
                send_message(chat_id, "✅ Файл загружен, ожидайте пополнение счета")
            
            # Ввод суммы админом
            elif 'text' in message and chat_id == ADMIN_ID and ADMIN_ID in waiting_for_amount:
                try:
                    amount = float(message['text'].replace(',', '.'))
                    if amount <= 0:
                        raise ValueError
                    
                    user_id = waiting_for_amount.pop(ADMIN_ID)
                    
                    db_execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
                    db_execute(
                        '''UPDATE transactions 
                           SET status = 'paid', amount = ? 
                           WHERE user_id = ? AND status = 'pending'
                           AND id = (SELECT MAX(id) FROM transactions WHERE user_id = ? AND status = 'pending')''',
                        (amount, user_id, user_id)
                    )
                    
                    result = db_fetchone('SELECT balance FROM users WHERE user_id = ?', (user_id,))
                    new_balance = result[0] if result else amount
                    
                    send_message(user_id, f"✅ Ваш баланс пополнен на ${amount:.2f}\n💰 Текущий баланс: ${new_balance:.2f}")
                    send_message(ADMIN_ID, f"✅ Баланс пользователя {user_id} пополнен на ${amount:.2f}")
                    
                except (ValueError, Exception) as e:
                    send_message(ADMIN_ID, "❌ Пожалуйста, введите корректную сумму (например 5.50)")
                    log(f"❌ Ошибка при вводе суммы: {e}")
        
        # Callback'и
        elif 'callback_query' in update:
            callback = update['callback_query']
            data = callback['data']
            msg = callback['message']
            
            log(f"🔘 Нажата кнопка: {data}")
            
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
                    
                    try:
                        edit_message_caption(
                            msg['chat']['id'],
                            msg['message_id'],
                            msg.get('caption', '') + "\n\n❌ ЗАБЛОКИРОВАНО"
                        )
                    except:
                        pass
                    
                    answer_callback(callback['id'], "Файл заблокирован")
            
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
                    
                    try:
                        edit_message_caption(
                            msg['chat']['id'],
                            msg['message_id'],
                            msg.get('caption', '') + "\n\n🔄 СЛЕТ"
                        )
                    except:
                        pass
                    
                    answer_callback(callback['id'], "Файл отклонён")
            
            elif data.startswith('amount_'):
                file_id = data.replace('amount_', '')
                user_data = file_user_map.get(file_id)
                
                if user_data:
                    waiting_for_amount[ADMIN_ID] = user_data['user_id']
                    send_message(ADMIN_ID, "💰 Введите сумму оплаты в долларах (например 5.50):")
                
                answer_callback(callback['id'])
            
            elif data == 'upload_tokens':
                send_message(msg['chat']['id'], "📎 Пожалуйста, загрузите файл токенов в формате .txt")
                answer_callback(callback['id'], "")
                
    except Exception as e:
        log(f"❌ Ошибка при обработке update: {str(e)}")
        import traceback
        log(traceback.format_exc())

def main():
    log("🤖 Запуск бота...")
    init_db()
    
    # Проверяем соединение с API
    log("🔍 Проверка соединения с Telegram API...")
    test_result = api_call('getMe', {})
    if test_result and test_result.get('ok'):
        bot_info = test_result['result']
        log(f"✅ Бот @{bot_info.get('username')} подключен!")
    else:
        log("❌ Не удалось подключиться к Telegram API")
        return
    
    offset = 0
    
    while True:
        try:
            req = urllib.request.Request(f"{API_URL}getUpdates?offset={offset}&timeout=30")
            response = urllib.request.urlopen(req, timeout=35)
            data = json.loads(response.read().decode('utf-8'))
            
            if data['ok'] and data['result']:
                log(f"📬 Получено {len(data['result'])} обновлений")
                for update in data['result']:
                    process_update(update)
                    offset = update['update_id'] + 1
            
        except Exception as e:
            log(f"❌ Ошибка в главном цикле: {str(e)}")
            time.sleep(5)

if __name__ == "__main__":
    main()

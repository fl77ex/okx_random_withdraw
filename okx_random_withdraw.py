import os
import random
import time
from datetime import datetime, timezone
import requests
import hmac
import hashlib
import base64
import json

from dotenv import load_dotenv
import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
api_key = os.getenv("OKX_API_KEY")
api_secret = os.getenv("OKX_API_SECRET")
api_passphrase = os.getenv("OKX_API_PASSPHRASE")
telegram_token = os.getenv("TELEGRAM_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

# Telegram бот
bot = telebot.TeleBot(telegram_token)

# Google Sheets
json_keyfile = 'credentials.json'
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
credentials = ServiceAccountCredentials.from_json_keyfile_name(json_keyfile, scope)
client = gspread.authorize(credentials)
sheet = client.open('Table name').worksheet('Sheet name')

BASE_URL = "https://www.okx.com"

def get_okx_timestamp():
    # Возвращает время в формате ISO 8601 с миллисекундами в UTC, пример: '2025-06-05T10:30:15.123Z'
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def get_signature(timestamp, method, request_path, body=''):
    message = f'{timestamp}{method.upper()}{request_path}{body}'
    mac = hmac.new(api_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    d = mac.digest()
    return base64.b64encode(d).decode()

def send_request(method, endpoint, params=None, body=''):
    request_path = endpoint
    if params:
        query_string = '&'.join(f'{k}={v}' for k, v in params.items())
        request_path += '?' + query_string
    else:
        query_string = ''

    timestamp = get_okx_timestamp()
    signature = get_signature(timestamp, method, request_path, body)

    headers = {
        'OK-ACCESS-KEY': api_key,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': api_passphrase,
        'Content-Type': 'application/json'
    }
    url = BASE_URL + request_path

    if method == 'GET':
        response = requests.get(url, headers=headers)
    elif method == 'POST':
        response = requests.post(url, headers=headers, data=body)
    else:
        raise ValueError("Unsupported method")

    try:
        return response.json()
    except Exception:
        print("Ошибка парсинга ответа:", response.text)
        return {}

def get_eth_balance():
    try:
        # В документации OKX для балансов - /api/v5/asset/balances
        res = send_request('GET', '/api/v5/asset/balances', {'ccy': 'ETH'})
        # res пример: {'code':'0','data':[{'ccy':'ETH','details':[{'availBal':'0.123'}]}]}
        print(res)
        
        if res.get('code') == '0':
            for item in res.get('data', []):
                if item.get('ccy') == 'ETH':
                    return float(item.get('availBal', '0'))
    except Exception as e:
        print(f"Ошибка при получении баланса: {e}")
    return 0.0

def get_withdrawal_fee(network):
    try:
        res = send_request('GET', '/api/v5/asset/currencies')
        #print(res)  # Для отладки

        if res.get('code') == '0':
            for item in res.get('data', []):
                if item.get('ccy') == 'ETH' and item.get('chain') == network:
                    fee = item.get('fee') or item.get('minFee') or 0
                    print(network, fee)
                    return float(fee)
    except Exception as e:
        print(f"Ошибка при получении комиссии: {e}")
    return None





def withdraw_eth(wallet, amount, network):
    fee = get_withdrawal_fee(network)
    
    if fee is None:
        print(f"Комиссия для {network} не найдена.")
        return False

    body_dict = {
        "ccy": "ETH",
        "amt": str(amount),
        "dest": "4",  # вывод на внешний адрес
        "toAddr": wallet,
        "chain": network,
        "fee": str(fee)
    }
    body = json.dumps(body_dict)

    try:
        res = send_request('POST', '/api/v5/asset/withdrawal', body=body)
        print(res)
        return res.get('code') == '0'
    except Exception as e:
        print(f"Ошибка при выводе: {e}")
        return False

def log_to_google_sheets(date_time, wallet, amount, network):
    row = [date_time, wallet, amount, network]
    sheet.append_row(row)

# Чтение кошельков
with open('wallets.txt', 'r') as f:
    wallets = f.read().splitlines()
    random.shuffle(wallets)

try:
    with open('success_wallets.txt', 'r') as f:
        success_wallets = set(f.read().splitlines())
except FileNotFoundError:
    success_wallets = set()

for wallet in wallets:
    if wallet in success_wallets:
        print(f"{wallet} уже обработан.")
        continue

    balance = get_eth_balance()

    if balance > 0.015:
        amount = round(random.uniform(0.0104, 0.0135), 6)
        network = random.choice(['ETH-Arbitrum One', 'ETH-Optimism', 'ETH-Base'])

        if withdraw_eth(wallet, amount, network):
            with open('success_wallets.txt', 'a') as f:
                f.write(wallet + '\n')

            date_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_to_google_sheets(date_time, wallet, amount, network)

            txt = f'✅ Withdraw from bal {balance:.4f} ETH\n{wallet}\n{amount:.6f} {network}'
            print(txt)
            bot.send_message(chat_id, txt)

            time.sleep(2)

        delay_min = random.randint(15, 60)
        for i in range(delay_min, 0, -1):
            msg = f'⏳ Next withdraw in {i}m'
            print(msg)
            bot.send_message(chat_id, msg)
            time.sleep(60)

        time.sleep(random.randint(120, 240))
    else:
        msg = f'❌ Balance too low ({balance:.4f} ETH)'
        print(msg)
        bot.send_message(chat_id, msg)
        time.sleep(0.5)


bot.send_message(chat_id, 'Jobs done')

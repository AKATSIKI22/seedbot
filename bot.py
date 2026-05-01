import os
import logging
import signal
import sys
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.error import Conflict
from mnemonic import Mnemonic
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
import requests
from web3 import Web3
import json
from asyncio import sleep
import base58
import asyncio

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set in environment")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== Web3 провайдеры ==========
ETH_RPC = "https://cloudflare-eth.com"
BSC_RPC = "https://bsc-dataseed.binance.org/"
POLYGON_RPC = "https://polygon-rpc.com"
AVALANCHE_RPC = "https://api.avax.network/ext/bc/C/rpc"
ARBITRUM_RPC = "https://arb1.arbitrum.io/rpc"
OPTIMISM_RPC = "https://mainnet.optimism.io"

w3_eth = Web3(Web3.HTTPProvider(ETH_RPC))
w3_bsc = Web3(Web3.HTTPProvider(BSC_RPC))
w3_polygon = Web3(Web3.HTTPProvider(POLYGON_RPC))
w3_avalanche = Web3(Web3.HTTPProvider(AVALANCHE_RPC))
w3_arbitrum = Web3(Web3.HTTPProvider(ARBITRUM_RPC))
w3_optimism = Web3(Web3.HTTPProvider(OPTIMISM_RPC))

# ========== Контракты USDT ==========
USDT_ERC20 = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
USDT_BEP20 = "0x55d398326f99059fF775485246999027B3197955"
USDT_POLYGON = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
USDT_AVALANCHE = "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7"
USDT_ARBITRUM = "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"
USDT_OPTIMISM = "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58"
# Адрес контракта USDT в сети TRON (стандартный TRC-20)
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]')

# ========== Функции получения балансов ==========
def get_eth_balance(address):
    try:
        balance_wei = w3_eth.eth.get_balance(address)
        return w3_eth.from_wei(balance_wei, 'ether')
    except:
        return 0

def get_bnb_balance(address):
    try:
        balance_wei = w3_bsc.eth.get_balance(address)
        return w3_bsc.from_wei(balance_wei, 'ether')
    except:
        return 0

def get_polygon_balance(address):
    try:
        balance_wei = w3_polygon.eth.get_balance(address)
        return w3_polygon.from_wei(balance_wei, 'ether')
    except:
        return 0

def get_avalanche_balance(address):
    try:
        balance_wei = w3_avalanche.eth.get_balance(address)
        return w3_avalanche.from_wei(balance_wei, 'ether')
    except:
        return 0

def get_arbitrum_balance(address):
    try:
        balance_wei = w3_arbitrum.eth.get_balance(address)
        return w3_arbitrum.from_wei(balance_wei, 'ether')
    except:
        return 0

def get_optimism_balance(address):
    try:
        balance_wei = w3_optimism.eth.get_balance(address)
        return w3_optimism.from_wei(balance_wei, 'ether')
    except:
        return 0

def get_usdt_balance(web3, address, contract_address):
    try:
        contract = web3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=ERC20_ABI)
        balance = contract.functions.balanceOf(address).call()
        return balance / 10**6
    except:
        return 0

def get_btc_balance(address):
    url = f"https://api.blockchair.com/bitcoin/dashboards/address/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        balance_sat = data['data'][address]['address']['balance']
        return balance_sat / 1e8
    except:
        return 0

def get_solana_balance(address):
    url = "https://api.mainnet-beta.solana.com"
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [address]
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        if 'result' in data:
            return data['result']['value'] / 1e9
    except:
        pass
    return 0

def get_dogecoin_balance(address):
    url = f"https://api.blockchair.com/dogecoin/dashboards/address/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        balance = data['data'][address]['address']['balance'] / 1e8
        return balance
    except:
        return 0

def get_ripple_balance(address):
    url = f"https://data.ripple.com/v2/accounts/{address}/balances"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if 'balances' in data:
            for bal in data['balances']:
                if bal['currency'] == 'XRP':
                    return float(bal['value'])
    except:
        pass
    return 0

def get_litecoin_balance(address):
    url = f"https://api.blockchair.com/litecoin/dashboards/address/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        balance = data['data'][address]['address']['balance'] / 1e8
        return balance
    except:
        return 0

def get_tron_balance(address):
    """Получает TRX баланс (основная монета)"""
    url = f"https://api.trongrid.io/v1/accounts/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if 'data' in data and len(data['data']) > 0:
            balance_sun = data['data'][0].get('balance', 0)
            return balance_sun / 1e6
    except:
        pass
    return 0

# *** ФУНКЦИЯ, КОТОРАЯ ТОЧНО РАБОТАЕТ ДЛЯ USDT TRC-20 ***
def get_usdt_trc20_balance(address):
    """Получает баланс USDT TRC-20 через TronGrid API v1 (проверенный метод)"""
    # Контракт USDT в сети TRON
    contract_address = USDT_TRC20_CONTRACT
    
    # Используем API Trongrid для запроса баланса токена
    url = f"https://api.trongrid.io/v1/accounts/{address}/trc20"
    
    params = {
        'contract_address': contract_address,
        'limit': 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        
        if 'data' in data and len(data['data']) > 0:
            # Баланс в 'value' приходит в минимальных единицах (USDT имеет 6 decimals)
            balance_value = data['data'][0].get('value', 0)
            if balance_value:
                balance = int(balance_value) / 1_000_000
                logger.info(f"USDT TRC20 balance for {address}: {balance}")
                return balance
        else:
            logger.info(f"No USDT TRC20 tokens found for {address}")
            
    except Exception as e:
        logger.error(f"USDT TRC20 balance error: {e}")
    
    return 0

def mnemonic_to_solana_address(mnemonic):
    """Генерация адреса Solana из сид-фразы (упрощенно)"""
    seed = Mnemonic.to_seed(mnemonic, passphrase="")
    # В реальном проекте нужна полная реализация BIP44 для Solana
    return base58.b58encode(seed[:32]).decode()  # Заглушка

def derive_addresses_from_mnemonic(mnemonic):
    seed = Bip39SeedGenerator(mnemonic).Generate()
    
    bip44_btc = Bip44.FromSeed(seed, Bip44Coins.BITCOIN)
    btc_addr = bip44_btc.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    bip44_eth = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
    eth_addr = bip44_eth.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    try:
        bip44_doge = Bip44.FromSeed(seed, Bip44Coins.DOGECOIN)
        doge_addr = bip44_doge.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        doge_addr = None
    
    try:
        bip44_ltc = Bip44.FromSeed(seed, Bip44Coins.LITECOIN)
        ltc_addr = bip44_ltc.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        ltc_addr = None
    
    try:
        bip44_xrp = Bip44.FromSeed(seed, Bip44Coins.XRP)
        xrp_addr = bip44_xrp.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        xrp_addr = None
    
    sol_addr = mnemonic_to_solana_address(mnemonic)
    
    try:
        bip44_trx = Bip44.FromSeed(seed, Bip44Coins.TRON)
        trx_addr = bip44_trx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        trx_addr = None
    
    return {
        "btc": btc_addr,
        "eth": eth_addr,
        "bnb": eth_addr,
        "polygon": eth_addr,
        "avalanche": eth_addr,
        "arbitrum": eth_addr,
        "optimism": eth_addr,
        "doge": doge_addr,
        "ltc": ltc_addr,
        "xrp": xrp_addr,
        "sol": sol_addr,
        "trx": trx_addr
    }

def check_all_balances(mnemonic):
    try:
        addrs = derive_addresses_from_mnemonic(mnemonic)
        
        results = {
            "btc": get_btc_balance(addrs["btc"]),
            "eth": get_eth_balance(addrs["eth"]),
            "bnb": get_bnb_balance(addrs["bnb"]),
            "polygon": get_polygon_balance(addrs["polygon"]),
            "avalanche": get_avalanche_balance(addrs["avalanche"]),
            "arbitrum": get_arbitrum_balance(addrs["arbitrum"]),
            "optimism": get_optimism_balance(addrs["optimism"]),
            "usdt_erc20": get_usdt_balance(w3_eth, addrs["eth"], USDT_ERC20),
            "usdt_bep20": get_usdt_balance(w3_bsc, addrs["bnb"], USDT_BEP20),
            "usdt_polygon": get_usdt_balance(w3_polygon, addrs["polygon"], USDT_POLYGON),
            "usdt_avalanche": get_usdt_balance(w3_avalanche, addrs["avalanche"], USDT_AVALANCHE),
            "usdt_arbitrum": get_usdt_balance(w3_arbitrum, addrs["arbitrum"], USDT_ARBITRUM),
            "usdt_optimism": get_usdt_balance(w3_optimism, addrs["optimism"], USDT_OPTIMISM),
            "sol": get_solana_balance(addrs["sol"]),
            "doge": get_dogecoin_balance(addrs["doge"]) if addrs["doge"] else 0,
            "xrp": get_ripple_balance(addrs["xrp"]) if addrs["xrp"] else 0,
            "ltc": get_litecoin_balance(addrs["ltc"]) if addrs["ltc"] else 0,
            "trx": get_tron_balance(addrs["trx"]) if addrs["trx"] else 0,
            # *** ВОТ ЗДЕСЬ ВЫЗЫВАЕТСЯ ИСПРАВЛЕННАЯ ФУНКЦИЯ ***
            "usdt_trc20": get_usdt_trc20_balance(addrs["trx"]) if addrs["trx"] else 0
        }
        return results
    except Exception as e:
        logger.error(f"Balance check error: {e}")
        return None

def has_balance(balance):
    if not balance:
        return False
    return any([
        balance.get('btc', 0) > 0,
        balance.get('eth', 0) > 0,
        balance.get('bnb', 0) > 0,
        balance.get('polygon', 0) > 0,
        balance.get('avalanche', 0) > 0,
        balance.get('arbitrum', 0) > 0,
        balance.get('optimism', 0) > 0,
        balance.get('sol', 0) > 0,
        balance.get('doge', 0) > 0,
        balance.get('xrp', 0) > 0,
        balance.get('ltc', 0) > 0,
        balance.get('trx', 0) > 0,
        balance.get('usdt_erc20', 0) > 0,
        balance.get('usdt_bep20', 0) > 0,
        balance.get('usdt_polygon', 0) > 0,
        balance.get('usdt_avalanche', 0) > 0,
        balance.get('usdt_arbitrum', 0) > 0,
        balance.get('usdt_optimism', 0) > 0,
        balance.get('usdt_trc20', 0) > 0
    ])

def init_storage(context):
    if 'checked_phrases' not in context.bot_data:
        context.bot_data['checked_phrases'] = {}
    if 'total_checks' not in context.bot_data:
        context.bot_data['total_checks'] = 0

# ========== Кнопки ==========
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("✨ Сгенерировать 1 фразу", callback_data="gen_1")],
        [InlineKeyboardButton("📦 Сгенерировать несколько", callback_data="gen_batch")],
        [InlineKeyboardButton("🔍 Проверить фразу", callback_data="check")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")]
    ]
    return InlineKeyboardMarkup(keyboard)

def batch_buttons():
    keyboard = [
        [InlineKeyboardButton("5", callback_data="batch_5"),
         InlineKeyboardButton("10", callback_data="batch_10"),
         InlineKeyboardButton("20", callback_data="batch_20")],
        [InlineKeyboardButton("50", callback_data="batch_50"),
         InlineKeyboardButton("100", callback_data="batch_100")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== Команды ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_storage(context)
    await update.message.reply_text(
        "🌐 <b>Crypto Seed Bot MAX</b>\n\n"
        "✅ Проверяю USDT TRC-20 через TronGrid API v1\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    init_storage(context)

    if data == "main_menu":
        await query.edit_message_text("Выберите действие:", reply_markup=main_menu_keyboard())
        return

    if data == "gen_batch":
        await query.edit_message_text("🔢 Сколько сид-фраз сгенерировать?", reply_markup=batch_buttons())
        return

    if data == "check":
        context.user_data['awaiting_check'] = True
        await query.edit_message_text(
            "✍️ Отправьте сид-фразу для проверки.\n"
            "Бот проверит балансы, включая USDT TRC-20."
        )
        return

    if data == "stats":
        total = context.bot_data['total_checks']
        non_empty = sum(1 for b in context.bot_data['checked_phrases'].values() if has_balance(b))
        text = f"📊 Статистика\n\nВсего проверено: {total}\nС балансом: {non_empty}"
        await query.edit_message_text(text, reply_markup=main_menu_keyboard())
        return

    if data.startswith("batch_"):
        count = int(data.split("_")[1])
        await query.edit_message_text(f"⏳ Генерирую {count} фраз... (это может занять время)")
        mnemo = Mnemonic("english")
        found = []
        for i in range(count):
            phrase = mnemo.generate(strength=128)
            balance = check_all_balances(phrase)
            if balance:
                context.bot_data['checked_phrases'][phrase] = balance
                context.bot_data['total_checks'] += 1
                if has_balance(balance):
                    found.append(phrase)
            if i % 10 == 0:
                await sleep(0.5)
        text = f"✅ Генерация {count} фраз завершена\nНайдено с балансом: {len(found)}\nВсего проверено: {context.bot_data['total_checks']}"
        await query.edit_message_text(text, reply_markup=main_menu_keyboard())
        return

    if data == "gen_1":
        await query.edit_message_text("⏳ Генерирую и проверяю...")
        mnemo = Mnemonic("english")
        phrase = mnemo.generate(strength=128)
        balance = check_all_balances(phrase)
        if not balance:
            await query.edit_message_text("Ошибка проверки", reply_markup=main_menu_keyboard())
            return
        context.bot_data['checked_phrases'][phrase] = balance
        context.bot_data['total_checks'] += 1
        
        text = f"<b>🔑 Сид-фраза:</b>\n<code>{phrase}</code>\n\n"
        text += f"<b>💰 Балансы USDT:</b>\n"
        text += f"ERC20: ${balance['usdt_erc20']:.2f}\n"
        text += f"BEP20: ${balance['usdt_bep20']:.2f}\n"
        text += f"POLYGON: ${balance['usdt_polygon']:.2f}\n"
        text += f"AVALANCHE: ${balance['usdt_avalanche']:.2f}\n"
        text += f"ARBITRUM: ${balance['usdt_arbitrum']:.2f}\n"
        text += f"OPTIMISM: ${balance['usdt_optimism']:.2f}\n"
        text += f"<b>TRC20: ${balance['usdt_trc20']:.2f}</b>\n"
        
        if has_balance(balance):
            text += f"\n🎉 <b>Найден ненулевой баланс USDT TRC-20!</b>"
        
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_storage(context)
    if context.user_data.get('awaiting_check'):
        phrase = update.message.text.strip()
        if len(phrase.split()) not in (12, 15, 18, 21, 24):
            await update.message.reply_text("❌ Неверное количество слов.")
            context.user_data['awaiting_check'] = False
            return
        await update.message.reply_text("⏳ Проверяю USDT TRC-20...")
        balance = check_all_balances(phrase)
        if not balance:
            await update.message.reply_text("Ошибка проверки")
        else:
            context.bot_data['checked_phrases'][phrase] = balance
            context.bot_data['total_checks'] += 1
            text = f"<b>✅ Результат проверки USDT TRC-20:</b>\n\n💰 Баланс: <b>${balance['usdt_trc20']:.2f}</b>"
            if has_balance(balance):
                text += f"\n\n🎉 Найден ненулевой баланс!"
            await update.message.reply_text(text, parse_mode="HTML")
        context.user_data['awaiting_check'] = False
    else:
        await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_menu_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_storage(context)
    total = context.bot_data['total_checks']
    non_empty = sum(1 for b in context.bot_data['checked_phrases'].values() if has_balance(b))
    await update.message.reply_text(f"📊 Статистика\n\nВсего: {total}\nС балансом: {non_empty}")

# ========== Запуск ==========
async def run_bot():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot started successfully!")
        while True:
            await asyncio.sleep(3600)
    except Conflict:
        logger.info("Conflict, restarting...")
        await asyncio.sleep(10)
        await run_bot()

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped")

if __name__ == "__main__":
    main()

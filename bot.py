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

ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]')

# ========== Функции получения балансов ==========
def get_eth_balance(address):
    try:
        balance_wei = w3_eth.eth.get_balance(address)
        return w3_eth.from_wei(balance_wei, 'ether')
    except:
        return None

def get_bnb_balance(address):
    try:
        balance_wei = w3_bsc.eth.get_balance(address)
        return w3_bsc.from_wei(balance_wei, 'ether')
    except:
        return None

def get_polygon_balance(address):
    try:
        balance_wei = w3_polygon.eth.get_balance(address)
        return w3_polygon.from_wei(balance_wei, 'ether')
    except:
        return None

def get_avalanche_balance(address):
    try:
        balance_wei = w3_avalanche.eth.get_balance(address)
        return w3_avalanche.from_wei(balance_wei, 'ether')
    except:
        return None

def get_arbitrum_balance(address):
    try:
        balance_wei = w3_arbitrum.eth.get_balance(address)
        return w3_arbitrum.from_wei(balance_wei, 'ether')
    except:
        return None

def get_optimism_balance(address):
    try:
        balance_wei = w3_optimism.eth.get_balance(address)
        return w3_optimism.from_wei(balance_wei, 'ether')
    except:
        return None

def get_usdt_balance(web3, address, contract_address):
    try:
        contract = web3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=ERC20_ABI)
        balance = contract.functions.balanceOf(address).call()
        return balance / 10**6
    except:
        return None

def get_btc_balance(address):
    url = f"https://api.blockchair.com/bitcoin/dashboards/address/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        balance_sat = data['data'][address]['address']['balance']
        return balance_sat / 1e8
    except:
        return None

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
    return None

def get_dogecoin_balance(address):
    url = f"https://api.blockchair.com/dogecoin/dashboards/address/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        balance = data['data'][address]['address']['balance'] / 1e8
        return balance
    except:
        return None

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
    return None

def get_litecoin_balance(address):
    url = f"https://api.blockchair.com/litecoin/dashboards/address/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        balance = data['data'][address]['address']['balance'] / 1e8
        return balance
    except:
        return None

def get_tron_balance(address):
    url = f"https://api.trongrid.io/v1/accounts/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if 'data' in data and len(data['data']) > 0:
            balance_sun = data['data'][0].get('balance', 0)
            return balance_sun / 1e6
    except:
        pass
    return None

def get_usdt_trc20_balance(address):
    url = f"https://api.trongrid.io/v1/accounts/{address}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if 'data' in data and len(data['data']) > 0:
            for trc20 in data['data'][0].get('trc20', []):
                if 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t' in trc20:
                    return int(trc20['TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t']) / 1e6
    except:
        pass
    return None

def mnemonic_to_solana_address(mnemonic):
    seed = Mnemonic.to_seed(mnemonic, passphrase="")
    return base58.b58encode(seed[:32]).decode()

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
        "btc": btc_addr, "eth": eth_addr, "bnb": eth_addr,
        "polygon": eth_addr, "avalanche": eth_addr,
        "arbitrum": eth_addr, "optimism": eth_addr,
        "doge": doge_addr, "ltc": ltc_addr, "xrp": xrp_addr,
        "sol": sol_addr, "trx": trx_addr
    }

def check_all_balances(mnemonic):
    try:
        addrs = derive_addresses_from_mnemonic(mnemonic)
        
        results = {
            "btc": get_btc_balance(addrs["btc"]) or 0,
            "eth": get_eth_balance(addrs["eth"]) or 0,
            "bnb": get_bnb_balance(addrs["bnb"]) or 0,
            "polygon": get_polygon_balance(addrs["polygon"]) or 0,
            "avalanche": get_avalanche_balance(addrs["avalanche"]) or 0,
            "arbitrum": get_arbitrum_balance(addrs["arbitrum"]) or 0,
            "optimism": get_optimism_balance(addrs["optimism"]) or 0,
            "usdt_erc20": get_usdt_balance(w3_eth, addrs["eth"], USDT_ERC20) or 0,
            "usdt_bep20": get_usdt_balance(w3_bsc, addrs["bnb"], USDT_BEP20) or 0,
            "usdt_polygon": get_usdt_balance(w3_polygon, addrs["polygon"], USDT_POLYGON) or 0,
            "usdt_avalanche": get_usdt_balance(w3_avalanche, addrs["avalanche"], USDT_AVALANCHE) or 0,
            "usdt_arbitrum": get_usdt_balance(w3_arbitrum, addrs["arbitrum"], USDT_ARBITRUM) or 0,
            "usdt_optimism": get_usdt_balance(w3_optimism, addrs["optimism"], USDT_OPTIMISM) or 0,
            "sol": get_solana_balance(addrs["sol"]) or 0,
            "doge": get_dogecoin_balance(addrs["doge"]) if addrs["doge"] else 0,
            "xrp": get_ripple_balance(addrs["xrp"]) if addrs["xrp"] else 0,
            "ltc": get_litecoin_balance(addrs["ltc"]) if addrs["ltc"] else 0,
            "trx": get_tron_balance(addrs["trx"]) if addrs["trx"] else 0,
            "usdt_trc20": get_usdt_trc20_balance(addrs["trx"]) if addrs["trx"] else 0,
            "addresses": addrs
        }
        return results
    except Exception as e:
        logger.error(f"Balance check error: {e}")
        return None

def has_balance(balance):
    return any([
        balance['btc'] > 0, balance['eth'] > 0, balance['bnb'] > 0,
        balance['polygon'] > 0, balance['avalanche'] > 0, balance['arbitrum'] > 0,
        balance['optimism'] > 0, balance['sol'] > 0, balance['doge'] > 0,
        balance['xrp'] > 0, balance['ltc'] > 0, balance['trx'] > 0,
        balance['usdt_erc20'] > 0, balance['usdt_bep20'] > 0,
        balance['usdt_polygon'] > 0, balance['usdt_avalanche'] > 0,
        balance['usdt_arbitrum'] > 0, balance['usdt_optimism'] > 0,
        balance['usdt_trc20'] > 0
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
        "Проверяю <b>12 сетей и 8 токенов USDT</b>\n\n"
        "⚠️ <b>Никогда не вводите реальные сид-фразы от кошельков с деньгами!</b>\n\n"
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
            "✍️ Отправьте сид-фразу (12 слов) для проверки.\n\n"
            "⚠️ <b>Внимание! Никогда не вводите фразу от вашего реального кошелька!</b>",
            parse_mode="HTML"
        )
        return

    if data == "stats":
        total = context.bot_data['total_checks']
        non_empty = sum(1 for b in context.bot_data['checked_phrases'].values() if has_balance(b))
        phrases = [p for p, b in context.bot_data['checked_phrases'].items() if has_balance(b)]
        
        text = f"📊 <b>СТАТИСТИКА</b>\n\n"
        text += f"🔹 Всего проверено: <b>{total}</b>\n"
        text += f"🔹 С балансом: <b>{non_empty}</b>\n"
        
        if phrases:
            text += f"\n<b>💰 Найденные фразы:</b>\n"
            for i, phrase in enumerate(phrases[:10], 1):
                text += f"{i}. <code>{phrase[:40]}...</code>\n"
        
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

    if data.startswith("batch_"):
        count = int(data.split("_")[1])
        await query.edit_message_text(f"⏳ Генерирую {count} фраз...")
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
        
        text = f"✅ Генерация {count} фраз завершена\n"
        text += f"Найдено с балансом: {len(found)}\n"
        text += f"Всего проверено: {context.bot_data['total_checks']}"
        
        await query.edit_message_text(text, reply_markup=main_menu_keyboard())
        return

    if data.startswith("gen_"):
        await query.edit_message_text("⏳ Генерирую...")
        mnemo = Mnemonic("english")
        phrase = mnemo.generate(strength=128)
        balance = check_all_balances(phrase)
        
        if not balance:
            await query.edit_message_text("Ошибка!", reply_markup=main_menu_keyboard())
            return
        
        context.bot_data['checked_phrases'][phrase] = balance
        context.bot_data['total_checks'] += 1
        
        text = f"<b>🔑 Сид-фраза:</b>\n<code>{phrase}</code>\n\n"
        text += f"<b>💰 Балансы:</b>\n"
        text += f"₿ BTC: {balance['btc']:.8f}\n"
        text += f"Ξ ETH: {balance['eth']:.6f}\n"
        text += f"🔶 BNB: {balance['bnb']:.6f}\n"
        text += f"◎ SOL: {balance['sol']:.6f}\n"
        text += f"🐕 DOGE: {balance['doge']:.8f}\n"
        text += f"🌞 TRX: {balance['trx']:.2f}\n\n"
        text += f"<b>💲 USDT TRC20:</b> ${balance['usdt_trc20']:.2f}\n"
        
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_storage(context)
    
    if context.user_data.get('awaiting_check'):
        phrase = update.message.text.strip()
        if len(phrase.split()) not in (12, 15, 18, 21, 24):
            await update.message.reply_text("❌ Фраза должна содержать 12 слов.")
            context.user_data['awaiting_check'] = False
            return
        
        await update.message.reply_text("⏳ Проверяю балансы...")
        balance = check_all_balances(phrase)
        
        if not balance:
            await update.message.reply_text("Ошибка проверки.")
        else:
            context.bot_data['checked_phrases'][phrase] = balance
            context.bot_data['total_checks'] += 1
            
            text = f"<b>🔑 Сид-фраза сохранена в статистику</b>\n\n"
            text += f"₿ BTC: {balance['btc']:.8f}\n"
            text += f"Ξ ETH: {balance['eth']:.6f}\n"
            text += f"◎ SOL: {balance['sol']:.6f}\n"
            
            if has_balance(balance):
                text += f"\n✅ <b>Найден ненулевой баланс!</b>"
            
            await update.message.reply_text(text, parse_mode="HTML")
        
        context.user_data['awaiting_check'] = False
    else:
        await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_menu_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_storage(context)
    total = context.bot_data['total_checks']
    non_empty = sum(1 for b in context.bot_data['checked_phrases'].values() if has_balance(b))
    await update.message.reply_text(f"📊 Статистика\n\nВсего: {total}\nС балансом: {non_empty}", reply_markup=main_menu_keyboard())

# ========== Защита от конфликтов ==========
async def run_bot():
    """Запуск бота с обработкой конфликтов"""
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Попытка запуска с обработкой ошибки Conflict
    try:
        logger.info("Starting bot...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query"])
        logger.info("Bot started successfully!")
        
        # Ожидаем завершения (бесконечно)
        while True:
            await asyncio.sleep(3600)
            
    except Conflict as e:
        logger.error(f"Conflict error: {e}")
        logger.info("Waiting 10 seconds and restarting...")
        await asyncio.sleep(10)
        await run_bot()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await asyncio.sleep(10)
        await run_bot()

def main():
    """Точка входа с обработкой сигналов"""
    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Запускаем бота с авто-перезапуском
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()

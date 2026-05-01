import os
import logging
import requests
import json
import base58
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from mnemonic import Mnemonic
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
from web3 import Web3
from solders.keypair import Keypair

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set in environment")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== Web3 провайдеры EVM ==========
ETH_RPC = "https://cloudflare-eth.com"
BSC_RPC = "https://bsc-dataseed.binance.com/"
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

# ========== Контракты токенов ==========
# Ethereum
USDT_ERC20 = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
USDC_ERC20 = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
# BSC
USDT_BEP20 = "0x55d398326f99059fF775485246999027B3197955"
USDC_BEP20 = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"
# Polygon
USDT_POLYGON = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
USDC_POLYGON = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
# Avalanche
USDT_AVALANCHE = "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7"
USDC_AVALANCHE = "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E"
# Arbitrum
USDT_ARBITRUM = "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"
USDC_ARBITRUM = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
# Optimism
USDT_OPTIMISM = "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58"
USDC_OPTIMISM = "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"
# Tron
USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]')

# ========== Функции балансов ==========
def get_evm_balance(web3, address):
    try:
        return web3.from_wei(web3.eth.get_balance(address), 'ether')
    except:
        return 0

def get_token_balance(web3, address, contract_address, decimals=6):
    try:
        contract = web3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=ERC20_ABI)
        return contract.functions.balanceOf(address).call() / 10**decimals
    except:
        return 0

def get_btc_balance(address):
    try:
        resp = requests.get(f"https://api.blockchair.com/bitcoin/dashboards/address/{address}", timeout=10)
        return resp.json()['data'][address]['address']['balance'] / 1e8
    except:
        return 0

def get_doge_balance(address):
    try:
        resp = requests.get(f"https://api.blockchair.com/dogecoin/dashboards/address/{address}", timeout=10)
        return resp.json()['data'][address]['address']['balance'] / 1e8
    except:
        return 0

def get_ltc_balance(address):
    try:
        resp = requests.get(f"https://api.blockchair.com/litecoin/dashboards/address/{address}", timeout=10)
        return resp.json()['data'][address]['address']['balance'] / 1e8
    except:
        return 0

def get_xrp_balance(address):
    try:
        resp = requests.get(f"https://data.ripple.com/v2/accounts/{address}/balances", timeout=10)
        data = resp.json()
        for bal in data.get('balances', []):
            if bal['currency'] == 'XRP':
                return float(bal['value'])
    except:
        pass
    return 0

def get_trx_balance(address):
    try:
        resp = requests.get(f"https://api.trongrid.io/v1/accounts/{address}", timeout=10)
        data = resp.json()
        return data['data'][0].get('balance', 0) / 1e6 if data.get('data') else 0
    except:
        return 0

def get_usdt_trc20(address):
    try:
        resp = requests.get(f"https://api.trongrid.io/v1/accounts/{address}/trc20", params={'contract_address': USDT_TRC20}, timeout=10)
        data = resp.json()
        return int(data['data'][0].get('value', 0)) / 1e6 if data.get('data') else 0
    except:
        return 0

def mnemonic_to_solana_keypair(mnemonic):
    """Генерирует Solana ключевую пару из сид-фразы"""
    seed = Mnemonic.to_seed(mnemonic, passphrase="")
    return Keypair().from_seed(seed[:32])

def get_solana_balance(address):
    """Получает SOL баланс"""
    try:
        resp = requests.post("https://api.mainnet-beta.solana.com", json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [str(address)]}, timeout=10)
        return resp.json()['result']['value'] / 1e9 if 'result' in resp.json() else 0
    except:
        return 0

def get_solana_token_balance(address, token_address):
    """Получает баланс SPL токена (USDT, USDC)"""
    try:
        resp = requests.post("https://api.mainnet-beta.solana.com", json={
            "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
            "params": [str(address), {"mint": token_address}, {"encoding": "json"}]
        }, timeout=10)
        data = resp.json()
        if 'result' in data and data['result']['value']:
            return data['result']['value'][0]['account']['data']['parsed']['info']['tokenAmount']['uiAmount'] or 0
    except:
        pass
    return 0

def derive_addresses(mnemonic):
    seed = Bip39SeedGenerator(mnemonic).Generate()
    
    # BTC
    bip44_btc = Bip44.FromSeed(seed, Bip44Coins.BITCOIN)
    btc_addr = bip44_btc.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    # EVM (ETH, BSC, Polygon, Avalanche, Arbitrum, Optimism)
    bip44_eth = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
    evm_addr = bip44_eth.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    # Dogecoin
    try:
        bip44_doge = Bip44.FromSeed(seed, Bip44Coins.DOGECOIN)
        doge_addr = bip44_doge.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        doge_addr = None
    
    # Litecoin
    try:
        bip44_ltc = Bip44.FromSeed(seed, Bip44Coins.LITECOIN)
        ltc_addr = bip44_ltc.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        ltc_addr = None
    
    # Ripple
    try:
        bip44_xrp = Bip44.FromSeed(seed, Bip44Coins.XRP)
        xrp_addr = bip44_xrp.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        xrp_addr = None
    
    # Tron
    try:
        bip44_trx = Bip44.FromSeed(seed, Bip44Coins.TRON)
        trx_addr = bip44_trx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        trx_addr = None
    
    # Solana
    keypair = mnemonic_to_solana_keypair(mnemonic)
    sol_addr = str(keypair.pubkey())
    
    return {
        "btc": btc_addr, "eth": evm_addr, "bnb": evm_addr,
        "polygon": evm_addr, "avalanche": evm_addr,
        "arbitrum": evm_addr, "optimism": evm_addr,
        "doge": doge_addr, "ltc": ltc_addr, "xrp": xrp_addr,
        "trx": trx_addr, "sol": sol_addr
    }

def check_all_balances(mnemonic):
    addrs = derive_addresses(mnemonic)
    
    balances = {
        # Основные монеты
        "btc": get_btc_balance(addrs["btc"]),
        "eth": get_evm_balance(w3_eth, addrs["eth"]),
        "bnb": get_evm_balance(w3_bsc, addrs["bnb"]),
        "polygon": get_evm_balance(w3_polygon, addrs["polygon"]),
        "avalanche": get_evm_balance(w3_avalanche, addrs["avalanche"]),
        "arbitrum": get_evm_balance(w3_arbitrum, addrs["arbitrum"]),
        "optimism": get_evm_balance(w3_optimism, addrs["optimism"]),
        "sol": get_solana_balance(addrs["sol"]),
        "doge": get_doge_balance(addrs["doge"]) if addrs["doge"] else 0,
        "xrp": get_xrp_balance(addrs["xrp"]) if addrs["xrp"] else 0,
        "ltc": get_ltc_balance(addrs["ltc"]) if addrs["ltc"] else 0,
        "trx": get_trx_balance(addrs["trx"]) if addrs["trx"] else 0,
        
        # USDT и USDC на всех сетях
        "usdt_erc20": get_token_balance(w3_eth, addrs["eth"], USDT_ERC20),
        "usdc_erc20": get_token_balance(w3_eth, addrs["eth"], USDC_ERC20),
        "usdt_bep20": get_token_balance(w3_bsc, addrs["bnb"], USDT_BEP20),
        "usdc_bep20": get_token_balance(w3_bsc, addrs["bnb"], USDC_BEP20),
        "usdt_polygon": get_token_balance(w3_polygon, addrs["polygon"], USDT_POLYGON),
        "usdc_polygon": get_token_balance(w3_polygon, addrs["polygon"], USDC_POLYGON),
        "usdt_avalanche": get_token_balance(w3_avalanche, addrs["avalanche"], USDT_AVALANCHE),
        "usdc_avalanche": get_token_balance(w3_avalanche, addrs["avalanche"], USDC_AVALANCHE),
        "usdt_arbitrum": get_token_balance(w3_arbitrum, addrs["arbitrum"], USDT_ARBITRUM),
        "usdc_arbitrum": get_token_balance(w3_arbitrum, addrs["arbitrum"], USDC_ARBITRUM),
        "usdt_optimism": get_token_balance(w3_optimism, addrs["optimism"], USDT_OPTIMISM),
        "usdc_optimism": get_token_balance(w3_optimism, addrs["optimism"], USDC_OPTIMISM),
        "usdt_trc20": get_usdt_trc20(addrs["trx"]) if addrs["trx"] else 0,
        
        "addresses": addrs
    }
    
    # Общая сумма в USD (упрощённые цены)
    total_usd = (
        balances["btc"] * 60000 + balances["eth"] * 3000 +
        balances["bnb"] * 300 + balances["polygon"] * 0.5 +
        balances["avalanche"] * 30 + balances["arbitrum"] * 3000 +
        balances["optimism"] * 3000 + balances["sol"] * 150 +
        balances["doge"] * 0.07 + balances["xrp"] * 0.5 +
        balances["ltc"] * 70 + balances["trx"] * 0.1 +
        balances["usdt_erc20"] + balances["usdc_erc20"] + balances["usdt_bep20"] +
        balances["usdc_bep20"] + balances["usdt_polygon"] + balances["usdc_polygon"] +
        balances["usdt_avalanche"] + balances["usdc_avalanche"] + balances["usdt_arbitrum"] +
        balances["usdc_arbitrum"] + balances["usdt_optimism"] + balances["usdc_optimism"] +
        balances["usdt_trc20"]
    )
    balances["total_usd"] = total_usd
    return balances

def has_balance(balances):
    return balances["total_usd"] > 0

# ========== Клавиатуры ==========
def main_menu():
    keyboard = [
        [InlineKeyboardButton("✨ Сгенерировать 1 фразу", callback_data="gen_1")],
        [InlineKeyboardButton("📦 Сгенерировать несколько", callback_data="gen_batch")],
        [InlineKeyboardButton("🔍 Проверить фразу", callback_data="check")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("🛑 Остановить генерацию", callback_data="stop_gen")]
    ]
    return InlineKeyboardMarkup(keyboard)

def batch_menu():
    keyboard = [
        [InlineKeyboardButton("10", callback_data="batch_10"),
         InlineKeyboardButton("25", callback_data="batch_25"),
         InlineKeyboardButton("50", callback_data="batch_50")],
        [InlineKeyboardButton("100", callback_data="batch_100"),
         InlineKeyboardButton("250", callback_data="batch_250"),
         InlineKeyboardButton("500", callback_data="batch_500")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== Команды ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 <b>Crypto Seed Bot ULTRA</b>\n\n"
        "✅ <b>Проверяю 20+ сетей и токенов:</b>\n"
        "₿ Bitcoin | Ξ Ethereum | 🔶 BNB | 🟣 Polygon\n"
        "🏔 Avalanche | 📦 Arbitrum | ⚡ Optimism\n"
        "◎ Solana | 🐕 Dogecoin | 💧 Ripple | ⚡ Litecoin\n"
        "🌞 Tron | 💲 USDT (ERC20, BEP20, Polygon, AVAX, ARB, OPT, TRC20)\n"
        "💲 USDC (ERC20, BEP20, Polygon, AVAX, ARB, OPT)\n\n"
        "📦 Массовая генерация → уведомления о каждой фразе\n"
        "📊 Финальный отчёт со списком найденных фраз\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await query.edit_message_text("Выберите действие:", reply_markup=main_menu())
        return

    if data == "gen_batch":
        await query.edit_message_text("🔢 Выберите количество фраз:", reply_markup=batch_menu())
        return

    if data.startswith("batch_"):
        count = int(data.split("_")[1])
        context.user_data['generating'] = True
        context.user_data['found_phrases'] = []
        context.user_data['checked'] = 0

        await query.edit_message_text(f"⏳ Начинаю генерацию {count} фраз.\nБуду присылать уведомления по каждой.\n\n🛑 Нажмите 'Остановить генерацию' чтобы прервать.")

        for i in range(1, count + 1):
            if not context.user_data.get('generating', True):
                await context.bot.send_message(chat_id=update.effective_chat.id, text="🛑 Генерация остановлена.")
                break

            mnemo = Mnemonic("english")
            phrase = mnemo.generate(strength=128)
            balances = check_all_balances(phrase)
            context.user_data['checked'] += 1

            if has_balance(balances):
                context.user_data['found_phrases'].append({
                    "phrase": phrase,
                    "total_usd": balances["total_usd"]
                })
                # Уведомление о найденном балансе
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"🎉 <b>НАЙДЕН БАЛАНС! 🎉</b>\n\n"
                         f"<code>{phrase}</code>\n"
                         f"💰 <b>Всего: ~${balances['total_usd']:.2f}</b>",
                    parse_mode="HTML"
                )
            else:
                if i % 10 == 0:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"🔍 Прогресс: {i}/{count} фраз проверено. Найдено: {len(context.user_data['found_phrases'])}"
                    )

            await asyncio.sleep(0.3)

        # Финальный отчёт
        found = context.user_data['found_phrases']
        report = f"✅ <b>ГЕНЕРАЦИЯ ЗАВЕРШЕНА</b>\n\n"
        report += f"📊 <b>Статистика:</b>\n"
        report += f"├ Проверено фраз: <b>{context.user_data['checked']}</b>\n"
        report += f"└ Найдено с балансом: <b>{len(found)}</b>\n"

        if found:
            report += f"\n💰 <b>СПИСОК НАЙДЕННЫХ ФРАЗ:</b>\n\n"
            for idx, item in enumerate(found[:20], 1):
                report += f"{idx}. <code>{item['phrase']}</code>\n"
                report += f"   └ 💵 ~${item['total_usd']:.2f}\n\n"
            if len(found) > 20:
                report += f"<i>... и ещё {len(found) - 20} фраз</i>\n"

        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode="HTML", reply_markup=main_menu())
        context.user_data['generating'] = False
        return

    if data == "stop_gen":
        context.user_data['generating'] = False
        await query.edit_message_text("🛑 Генерация остановлена.", reply_markup=main_menu())
        return

    if data == "check":
        context.user_data['awaiting_check'] = True
        await query.edit_message_text(
            "✍️ <b>Отправьте сид-фразу (12 слов) для проверки</b>\n\n"
            "Пример: abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about\n\n"
            "Я проверю ВСЕ сети и токены.",
            parse_mode="HTML"
        )
        return

    if data == "stats":
        stats = context.bot_data.get('stats', {'total': 0, 'found': 0})
        await query.edit_message_text(
            f"📊 <b>Общая статистика бота</b>\n\n"
            f"├ Всего проверено фраз: <b>{stats.get('total', 0)}</b>\n"
            f"└ Найдено с балансом: <b>{stats.get('found', 0)}</b>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        return

    if data == "gen_1":
        await query.edit_message_text("⏳ Генерирую и проверяю... (20+ сетей)")
        mnemo = Mnemonic("english")
        phrase = mnemo.generate(strength=128)
        balances = check_all_balances(phrase)

        stats = context.bot_data.get('stats', {'total': 0, 'found': 0})
        stats['total'] += 1
        if has_balance(balances):
            stats['found'] += 1
        context.bot_data['stats'] = stats

        text = f"<b>🔑 Сид-фраза:</b>\n<code>{phrase}</code>\n\n"
        text += f"<b>💰 Основные балансы:</b>\n"
        text += f"₿ BTC: {balances['btc']:.8f}\n"
        text += f"Ξ ETH: {balances['eth']:.6f}\n"
        text += f"🔶 BNB: {balances['bnb']:.6f}\n"
        text += f"🟣 POLYGON: {balances['polygon']:.6f}\n"
        text += f"◎ SOL: {balances['sol']:.6f}\n"
        text += f"🌞 TRX: {balances['trx']:.2f}\n"
        text += f"🐕 DOGE: {balances['doge']:.8f}\n\n"
        text += f"<b>💲 USDT (на всех сетях):</b>\n"
        text += f"├ ERC20: ${balances['usdt_erc20']:.2f}\n"
        text += f"├ BEP20: ${balances['usdt_bep20']:.2f}\n"
        text += f"├ POLYGON: ${balances['usdt_polygon']:.2f}\n"
        text += f"├ TRC20: ${balances['usdt_trc20']:.2f}\n"
        text += f"└ ... и другие\n\n"
        text += f"💵 <b>ИТОГО: ~${balances['total_usd']:.2f}</b>"

        if has_balance(balances):
            text += f"\n\n🎉 <b>НАЙДЕН НЕНУЛЕВОЙ БАЛАНС!</b>"

        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu())
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_check'):
        phrase = update.message.text.strip()
        if len(phrase.split()) not in (12, 15, 18, 21, 24):
            await update.message.reply_text("❌ Нужно 12, 15, 18, 21 или 24 слова.")
            context.user_data['awaiting_check'] = False
            return

        await update.message.reply_text("⏳ Проверяю 20+ сетей...")
        balances = check_all_balances(phrase)

        stats = context.bot_data.get('stats', {'total': 0, 'found': 0})
        stats['total'] += 1
        if has_balance(balances):
            stats['found'] += 1
        context.bot_data['stats'] = stats

        text = f"<b>✅ Результат проверки:</b>\n\n"
        text += f"₿ BTC: {balances['btc']:.8f}\n"
        text += f"◎ SOL: {balances['sol']:.6f}\n"
        text += f"🌞 TRX: {balances['trx']:.2f}\n"
        text += f"💲 USDT TRC20: ${balances['usdt_trc20']:.2f}\n"
        text += f"💵 <b>ИТОГО: ~${balances['total_usd']:.2f}</b>\n\n"
        text += f"📍 TRON адрес: <code>{balances['addresses']['trx']}</code>\n"
        text += f"📊 Всего проверено: {stats['total']} | Найдено: {stats['found']}"

        if has_balance(balances):
            text += f"\n\n🎉 <b>НАЙДЕН БАЛАНС!</b>"

        await update.message.reply_text(text, parse_mode="HTML")
        context.user_data['awaiting_check'] = False
    else:
        await update.message.reply_text("Используйте кнопки меню 👇", reply_markup=main_menu())

# ========== Запуск ==========
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if 'stats' not in app.bot_data:
        app.bot_data['stats'] = {'total': 0, 'found': 0}

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

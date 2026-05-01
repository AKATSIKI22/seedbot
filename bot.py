import os
import logging
import requests
import json
import base58
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from mnemonic import Mnemonic
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
from web3 import Web3

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set in environment")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== Web3 провайдеры ==========
ETH_RPC = "https://cloudflare-eth.com"
BSC_RPC = "https://bsc-dataseed.binance.com/"
POLYGON_RPC = "https://polygon-rpc.com"

w3_eth = Web3(Web3.HTTPProvider(ETH_RPC))
w3_bsc = Web3(Web3.HTTPProvider(BSC_RPC))
w3_polygon = Web3(Web3.HTTPProvider(POLYGON_RPC))

# ========== Контракты USDT ==========
USDT_ERC20 = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
USDT_BEP20 = "0x55d398326f99059fF775485246999027B3197955"
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
        data = resp.json()
        return data['data'][address]['address']['balance'] / 1e8
    except:
        return 0

def get_solana_balance(address):
    try:
        resp = requests.post(
            "https://api.mainnet-beta.solana.com",
            json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]},
            timeout=10
        )
        data = resp.json()
        return data['result']['value'] / 1e9 if 'result' in data else 0
    except:
        return 0

def get_trx_balance(address):
    try:
        resp = requests.get(f"https://api.trongrid.io/v1/accounts/{address}", timeout=10)
        data = resp.json()
        return data['data'][0].get('balance', 0) / 1e6 if data.get('data') else 0
    except:
        return 0

def get_usdt_trc20_balance(address):
    try:
        resp = requests.get(
            f"https://api.trongrid.io/v1/accounts/{address}/trc20",
            params={'contract_address': USDT_TRC20},
            timeout=10
        )
        data = resp.json()
        return int(data['data'][0].get('value', 0)) / 1e6 if data.get('data') else 0
    except:
        return 0

def mnemonic_to_solana_address(mnemonic):
    seed = Mnemonic.to_seed(mnemonic, passphrase="")
    return base58.b58encode(seed[:32]).decode()

def derive_addresses(mnemonic):
    seed = Bip39SeedGenerator(mnemonic).Generate()
    
    bip44_btc = Bip44.FromSeed(seed, Bip44Coins.BITCOIN)
    btc_addr = bip44_btc.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    bip44_eth = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
    evm_addr = bip44_eth.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    try:
        bip44_trx = Bip44.FromSeed(seed, Bip44Coins.TRON)
        trx_addr = bip44_trx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        trx_addr = None
    
    sol_addr = mnemonic_to_solana_address(mnemonic)
    
    return {
        "btc": btc_addr,
        "eth": evm_addr,
        "bnb": evm_addr,
        "polygon": evm_addr,
        "trx": trx_addr,
        "sol": sol_addr
    }

def check_all_balances(mnemonic):
    addrs = derive_addresses(mnemonic)
    
    btc = get_btc_balance(addrs["btc"])
    eth = get_evm_balance(w3_eth, addrs["eth"])
    bnb = get_evm_balance(w3_bsc, addrs["bnb"])
    polygon = get_evm_balance(w3_polygon, addrs["polygon"])
    sol = get_solana_balance(addrs["sol"])
    trx = get_trx_balance(addrs["trx"]) if addrs["trx"] else 0
    
    usdt_erc20 = get_token_balance(w3_eth, addrs["eth"], USDT_ERC20)
    usdt_bep20 = get_token_balance(w3_bsc, addrs["bnb"], USDT_BEP20)
    usdt_trc20 = get_usdt_trc20_balance(addrs["trx"]) if addrs["trx"] else 0
    
    total_usd = (
        btc * 60000 + eth * 3000 + bnb * 300 +
        polygon * 0.5 + sol * 150 + trx * 0.1 +
        usdt_erc20 + usdt_bep20 + usdt_trc20
    )
    
    return {
        "btc": btc, "eth": eth, "bnb": bnb, "polygon": polygon,
        "sol": sol, "trx": trx,
        "usdt_erc20": usdt_erc20, "usdt_bep20": usdt_bep20, "usdt_trc20": usdt_trc20,
        "total_usd": total_usd,
        "addresses": addrs
    }

def has_balance(balances):
    return balances["total_usd"] > 0

# ========== Клавиатура с увеличенным количеством ==========
def main_menu():
    keyboard = [
        [KeyboardButton("✨ 1 фразу")],
        [KeyboardButton("📦 5"), KeyboardButton("📦 10"), KeyboardButton("📦 25")],
        [KeyboardButton("📦 50"), KeyboardButton("📦 100"), KeyboardButton("📦 500")],
        [KeyboardButton("📦 1000"), KeyboardButton("📦 2000")],
        [KeyboardButton("🔍 Проверить фразу")],
        [KeyboardButton("📊 Статистика"), KeyboardButton("🛑 Остановить")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# ========== Генерация и сохранение ==========
async def generate_batch(update: Update, context: ContextTypes.DEFAULT_TYPE, count: int):
    context.user_data['generating'] = True
    context.user_data['all_phrases'] = []
    context.user_data['found_phrases'] = []
    context.user_data['checked'] = 0

    await update.message.reply_text(
        f"⏳ <b>Начинаю генерацию {count} фраз</b>\n\n"
        f"Каждая фраза придёт отдельно.",
        parse_mode="HTML"
    )

    for i in range(1, count + 1):
        if not context.user_data.get('generating', True):
            await update.message.reply_text("🛑 Остановлено.")
            break

        mnemo = Mnemonic("english")
        phrase = mnemo.generate(strength=128)
        balances = check_all_balances(phrase)
        context.user_data['checked'] += 1

        context.user_data['all_phrases'].append({
            "phrase": phrase,
            "balances": balances
        })

        if has_balance(balances):
            context.user_data['found_phrases'].append({
                "phrase": phrase,
                "total_usd": balances['total_usd']
            })
            text = f"🎉 <b>НАЙДЕН БАЛАНС!</b> ({i}/{count})\n\n<code>{phrase}</code>\n💵 ~${balances['total_usd']:.2f}"
        else:
            text = f"❌ {i}/{count}\n<code>{phrase}</code>"

        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())
        await asyncio.sleep(0.15)

    # Финальный отчёт и файл
    found = context.user_data['found_phrases']
    all_phrases = context.user_data['all_phrases']

    report = f"✅ <b>ГОТОВО</b>\n\n"
    report += f"📊 Проверено: {context.user_data['checked']}\n"
    report += f"💰 Найдено: {len(found)}\n\n"

    if found:
        report += f"<b>СПИСОК НАЙДЕННЫХ:</b>\n"
        for idx, item in enumerate(found[:15], 1):
            report += f"{idx}. {item['phrase'][:30]}... (${item['total_usd']:.2f})\n"
        if len(found) > 15:
            report += f"\n<i>+ ещё {len(found) - 15} фраз</i>\n"

    await update.message.reply_text(report, parse_mode="HTML", reply_markup=main_menu())

    # Отправляем файл со всеми фразами
    if all_phrases:
        filename = f"seed_phrases_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            for idx, item in enumerate(all_phrases, 1):
                b = item["balances"]
                f.write(f"{idx}. Фраза: {item['phrase']}\n")
                f.write(f"   BTC: {b['btc']:.8f} | ETH: {b['eth']:.6f} | BNB: {b['bnb']:.6f}\n")
                f.write(f"   MATIC: {b['polygon']:.6f} | SOL: {b['sol']:.6f} | TRX: {b['trx']:.2f}\n")
                f.write(f"   USDT ERC20: ${b['usdt_erc20']:.2f} | BEP20: ${b['usdt_bep20']:.2f} | TRC20: ${b['usdt_trc20']:.2f}\n")
                f.write(f"   Итого: ${b['total_usd']:.2f}\n")
                f.write(f"   BTC адрес: {b['addresses']['btc']}\n")
                f.write(f"   EVM адрес: {b['addresses']['eth']}\n")
                f.write(f"   TRON адрес: {b['addresses']['trx']}\n")
                f.write(f"   SOL адрес: {b['addresses']['sol']}\n")
                f.write("-" * 50 + "\n")
        
        with open(filename, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption=f"📄 Все {len(all_phrases)} сид-фраз в файле"
            )
        os.remove(filename)

    context.user_data['generating'] = False

# ========== Обработка сообщений ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "✨ 1 фразу":
        await generate_batch(update, context, 1)
    elif text == "📦 5":
        await generate_batch(update, context, 5)
    elif text == "📦 10":
        await generate_batch(update, context, 10)
    elif text == "📦 25":
        await generate_batch(update, context, 25)
    elif text == "📦 50":
        await generate_batch(update, context, 50)
    elif text == "📦 100":
        await generate_batch(update, context, 100)
    elif text == "📦 500":
        await generate_batch(update, context, 500)
    elif text == "📦 1000":
        await generate_batch(update, context, 1000)
    elif text == "📦 2000":
        await generate_batch(update, context, 2000)
    elif text == "🔍 Проверить фразу":
        context.user_data['awaiting_check'] = True
        await update.message.reply_text("✍️ Отправьте сид-фразу (12 слов):")
    elif text == "📊 Статистика":
        stats = context.bot_data.get('stats', {'total': 0, 'found': 0})
        await update.message.reply_text(
            f"📊 Статистика\n\nВсего проверено: {stats.get('total', 0)}\nНайдено: {stats.get('found', 0)}",
            reply_markup=main_menu()
        )
    elif text == "🛑 Остановить":
        context.user_data['generating'] = False
        await update.message.reply_text("🛑 Остановлено.", reply_markup=main_menu())
    elif context.user_data.get('awaiting_check'):
        phrase = text.strip()
        if len(phrase.split()) in (12, 15, 18, 21, 24):
            await update.message.reply_text("⏳ Проверяю...")
            balances = check_all_balances(phrase)
            stats = context.bot_data.get('stats', {'total': 0, 'found': 0})
            stats['total'] += 1
            if has_balance(balances):
                stats['found'] += 1
            context.bot_data['stats'] = stats
            result = f"✅ Результат\n\n"
            result += f"BTC: {balances['btc']:.8f}\nETH: {balances['eth']:.6f}\nBNB: {balances['bnb']:.6f}\n"
            result += f"MATIC: {balances['polygon']:.6f}\nSOL: {balances['sol']:.6f}\nTRX: {balances['trx']:.2f}\n\n"
            result += f"USDT ERC20: ${balances['usdt_erc20']:.2f}\nUSDT BEP20: ${balances['usdt_bep20']:.2f}\nUSDT TRC20: ${balances['usdt_trc20']:.2f}\n"
            result += f"💰 Итого: ${balances['total_usd']:.2f}"
            await update.message.reply_text(result, reply_markup=main_menu())
        else:
            await update.message.reply_text("❌ Некорректная сид-фраза.")
        context.user_data['awaiting_check'] = False
    else:
        await update.message.reply_text("Нажмите на кнопку", reply_markup=main_menu())

# ========== Старт ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Crypto Seed Bot\n\n✅ BTC, ETH, BNB, MATIC, SOL, TRX\n💲 USDT (ERC20, BEP20, TRC20)\n\n⬇️ Нажмите кнопку:",
        reply_markup=main_menu()
    )

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if 'stats' not in app.bot_data:
        app.bot_data['stats'] = {'total': 0, 'found': 0}

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

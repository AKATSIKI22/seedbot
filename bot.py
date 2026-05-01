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
    
    # Bitcoin
    bip44_btc = Bip44.FromSeed(seed, Bip44Coins.BITCOIN)
    btc_addr = bip44_btc.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    # EVM (ETH, BSC, Polygon)
    bip44_eth = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
    evm_addr = bip44_eth.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    # Tron
    try:
        bip44_trx = Bip44.FromSeed(seed, Bip44Coins.TRON)
        trx_addr = bip44_trx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        trx_addr = None
    
    # Solana
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
    
    # Основные монеты
    btc = get_btc_balance(addrs["btc"])
    eth = get_evm_balance(w3_eth, addrs["eth"])
    bnb = get_evm_balance(w3_bsc, addrs["bnb"])
    polygon = get_evm_balance(w3_polygon, addrs["polygon"])
    sol = get_solana_balance(addrs["sol"])
    trx = get_trx_balance(addrs["trx"]) if addrs["trx"] else 0
    
    # USDT на всех сетях
    usdt_erc20 = get_token_balance(w3_eth, addrs["eth"], USDT_ERC20)
    usdt_bep20 = get_token_balance(w3_bsc, addrs["bnb"], USDT_BEP20)
    usdt_trc20 = get_usdt_trc20_balance(addrs["trx"]) if addrs["trx"] else 0
    
    # Общая сумма в USD
    total_usd = (
        btc * 60000 +
        eth * 3000 +
        bnb * 300 +
        polygon * 0.5 +
        sol * 150 +
        trx * 0.1 +
        usdt_erc20 + usdt_bep20 + usdt_trc20
    )
    
    return {
        "btc": btc,
        "eth": eth,
        "bnb": bnb,
        "polygon": polygon,
        "sol": sol,
        "trx": trx,
        "usdt_erc20": usdt_erc20,
        "usdt_bep20": usdt_bep20,
        "usdt_trc20": usdt_trc20,
        "total_usd": total_usd,
        "addresses": addrs
    }

def has_balance(balances):
    return balances["total_usd"] > 0

# ========== Клавиатура ==========
def main_menu():
    keyboard = [
        [InlineKeyboardButton("✨ Сгенерировать 1 фразу", callback_data="gen_1")],
        [InlineKeyboardButton("📦 Сгенерировать 5 фраз", callback_data="batch_5")],
        [InlineKeyboardButton("📦 Сгенерировать 10 фраз", callback_data="batch_10")],
        [InlineKeyboardButton("📦 Сгенерировать 25 фраз", callback_data="batch_25")],
        [InlineKeyboardButton("📦 Сгенерировать 50 фраз", callback_data="batch_50")],
        [InlineKeyboardButton("📦 Сгенерировать 100 фраз", callback_data="batch_100")],
        [InlineKeyboardButton("🔍 Проверить фразу", callback_data="check")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("🛑 Остановить генерацию", callback_data="stop_gen")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== Команды ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 <b>Crypto Seed Bot</b>\n\n"
        "✅ <b>Проверяю:</b>\n"
        "₿ Bitcoin | Ξ Ethereum | 🔶 BNB\n"
        "🟣 Polygon | ◎ Solana | 🌞 Tron\n"
        "💲 USDT (ERC20, BEP20, TRC20)\n\n"
        "📦 При массовой генерации КАЖДАЯ фраза приходит отдельно\n"
        "📊 В конце — финальный отчёт\n\n"
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

    if data == "check":
        context.user_data['awaiting_check'] = True
        await query.edit_message_text(
            "✍️ <b>Отправьте сид-фразу (12 слов)</b>\n\n"
            "Пример: abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
            parse_mode="HTML"
        )
        return

    if data == "stats":
        stats = context.bot_data.get('stats', {'total': 0, 'found': 0})
        await query.edit_message_text(
            f"📊 <b>Статистика</b>\n\n"
            f"├ Всего проверено: {stats.get('total', 0)}\n"
            f"└ Найдено с балансом: {stats.get('found', 0)}",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        return

    if data == "stop_gen":
        context.user_data['generating'] = False
        await query.edit_message_text("🛑 Генерация остановлена.", reply_markup=main_menu())
        return

    if data == "gen_1":
        await query.edit_message_text("⏳ Генерирую...")
        mnemo = Mnemonic("english")
        phrase = mnemo.generate(strength=128)
        balances = check_all_balances(phrase)

        stats = context.bot_data.get('stats', {'total': 0, 'found': 0})
        stats['total'] += 1
        if has_balance(balances):
            stats['found'] += 1
        context.bot_data['stats'] = stats

        text = f"<b>🔑 Сид-фраза:</b>\n<code>{phrase}</code>\n\n"
        text += f"<b>💰 Балансы:</b>\n"
        text += f"₿ BTC: {balances['btc']:.8f}\n"
        text += f"Ξ ETH: {balances['eth']:.6f}\n"
        text += f"🔶 BNB: {balances['bnb']:.6f}\n"
        text += f"🟣 MATIC: {balances['polygon']:.6f}\n"
        text += f"◎ SOL: {balances['sol']:.6f}\n"
        text += f"🌞 TRX: {balances['trx']:.2f}\n\n"
        text += f"<b>💲 USDT:</b>\n"
        text += f"├ ERC20: ${balances['usdt_erc20']:.2f}\n"
        text += f"├ BEP20: ${balances['usdt_bep20']:.2f}\n"
        text += f"└ TRC20: ${balances['usdt_trc20']:.2f}\n\n"
        text += f"💵 <b>ИТОГО: ~${balances['total_usd']:.2f}</b>"

        if has_balance(balances):
            text += f"\n\n🎉 <b>НАЙДЕН НЕНУЛЕВОЙ БАЛАНС!</b>"

        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu())
        return

    if data.startswith("batch_"):
        count = int(data.split("_")[1])
        context.user_data['generating'] = True
        context.user_data['found_phrases'] = []
        context.user_data['checked'] = 0

        await query.edit_message_text(
            f"⏳ <b>Начинаю генерацию {count} фраз</b>\n\n"
            f"Каждая фраза придёт отдельным сообщением.\n"
            f"🛑 Нажмите 'Остановить генерацию' чтобы прервать.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

        for i in range(1, count + 1):
            if not context.user_data.get('generating', True):
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="🛑 Генерация остановлена.",
                    reply_markup=main_menu()
                )
                break

            mnemo = Mnemonic("english")
            phrase = mnemo.generate(strength=128)
            balances = check_all_balances(phrase)
            context.user_data['checked'] += 1

            if has_balance(balances):
                context.user_data['found_phrases'].append({
                    "phrase": phrase,
                    "usdt_erc20": balances['usdt_erc20'],
                    "usdt_bep20": balances['usdt_bep20'],
                    "usdt_trc20": balances['usdt_trc20'],
                    "total_usd": balances['total_usd']
                })
                text = f"🎉 <b>НАЙДЕН БАЛАНС!</b> ({i}/{count})\n\n"
                text += f"<code>{phrase}</code>\n\n"
                text += f"💲 USDT ERC20: ${balances['usdt_erc20']:.2f}\n"
                text += f"💲 USDT BEP20: ${balances['usdt_bep20']:.2f}\n"
                text += f"💲 USDT TRC20: ${balances['usdt_trc20']:.2f}\n"
                text += f"💵 <b>~${balances['total_usd']:.2f}</b>"
            else:
                text = f"❌ <b>Фраза {i}/{count}</b> — пустая\n\n"
                text += f"<code>{phrase}</code>"

            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML")
            await asyncio.sleep(0.2)

        found = context.user_data['found_phrases']
        report = f"✅ <b>ГЕНЕРАЦИЯ ЗАВЕРШЕНА</b>\n\n"
        report += f"📊 <b>Статистика:</b>\n"
        report += f"├ Проверено фраз: {context.user_data['checked']}\n"
        report += f"└ Найдено с балансом: {len(found)}\n"

        if found:
            report += f"\n💰 <b>СПИСОК НАЙДЕННЫХ ФРАЗ:</b>\n\n"
            for idx, item in enumerate(found[:20], 1):
                report += f"{idx}. <code>{item['phrase']}</code>\n"
                report += f"   └ 💵 ~${item['total_usd']:.2f}\n\n"
            if len(found) > 20:
                report += f"<i>... и ещё {len(found) - 20} фраз</i>"

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=report,
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        context.user_data['generating'] = False
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_check'):
        phrase = update.message.text.strip()
        words = phrase.split()
        if len(words) not in (12, 15, 18, 21, 24):
            await update.message.reply_text(f"❌ Нужно 12, 15, 18, 21 или 24 слова. У вас {len(words)}.")
            context.user_data['awaiting_check'] = False
            return

        await update.message.reply_text("⏳ Проверяю балансы...")
        balances = check_all_balances(phrase)

        stats = context.bot_data.get('stats', {'total': 0, 'found': 0})
        stats['total'] += 1
        if has_balance(balances):
            stats['found'] += 1
        context.bot_data['stats'] = stats

        text = f"<b>✅ Результат проверки</b>\n\n"
        text += f"₿ BTC: {balances['btc']:.8f}\n"
        text += f"◎ SOL: {balances['sol']:.6f}\n"
        text += f"🌞 TRX: {balances['trx']:.2f}\n\n"
        text += f"<b>💲 USDT:</b>\n"
        text += f"├ ERC20: ${balances['usdt_erc20']:.2f}\n"
        text += f"├ BEP20: ${balances['usdt_bep20']:.2f}\n"
        text += f"└ TRC20: ${balances['usdt_trc20']:.2f}\n\n"
        text += f"💵 <b>ИТОГО: ~${balances['total_usd']:.2f}</b>\n\n"
        text += f"📍 TRON: <code>{balances['addresses']['trx']}</code>\n"
        text += f"📊 Статистика: проверено {stats['total']}, найдено {stats['found']}"

        if has_balance(balances):
            text += f"\n\n🎉 <b>НАЙДЕН НЕНУЛЕВОЙ БАЛАНС!</b>"

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

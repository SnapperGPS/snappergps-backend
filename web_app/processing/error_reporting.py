from telegram import Bot
import config


def report_error(error_text : str) -> None:
    """Send me a Telegram message if somethiung went wrong.

    Change this if you do not want to use Telegram for error reporting.
    
    Args:
        error_text (str): The error message to send.
    """
    Bot(config.server_bot_token).send_message(
        chat_id=config.server_bot_contact_chat_id,
        text=error_text)

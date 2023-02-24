# Telegram bot for user notifications
import telegram_bot
# Email bot
from email_bot import EmailBot
# Push notification bot
from push_notification_bot import PushNotificationBot
# Credentials/secrets/tokens
import config


class UserNotifications:
    """SnapperGPS user notfication routines.

    Author: Jonas Beuchert
    """

    def __init__(self, run_telegram_bot: bool) -> None:
        """Start the user notification bots.

        Start Telegram bot if config.use_telegram_notifications is True and run_telegram_bot is True.
        Start email bot if config.use_email_notifications is True.
        Start push notification bot if config.use_push_notifications is True.

        Args:
            run_telegram_bot (bool): Whether to run the Telegram bot.
        """
        self.run_telegram_bot = run_telegram_bot
        if config.use_telegram_notifications and run_telegram_bot:
            # Set up SnapperGPS Telegram bot for user notification
            self.t_bot = telegram_bot.TelegramBot()

        if config.use_email_notifications:
            # Set up SnapperGPS email bot for user notification
            self.e_bot = EmailBot()

        if config.use_push_notifications:
            # Set up SnapperGPS bot for user push notification
            self.p_bot = PushNotificationBot()


    def send_notifications(self, cursor, upload_id: str) -> None:
        """Send user notification via Telegram, e-mail, and/or push notification.

        Args:

            cursor (psycopg2.extensions.cursor): Database cursor.
            upload_id (str): The upload ID.
        """
        if config.use_push_notifications:
            # Send push message to user
            self.p_bot.send_msg(upload_id)

        if config.use_email_notifications:
            # Send e-mail to user
            self.e_bot.final_email(cursor, upload_id)

        if config.use_telegram_notifications:
            # Send Telegram message to user
            if self.run_telegram_bot:
                self.t_bot.send_msg(upload_id)
            else:
                telegram_bot.send_msg_no_bot(cursor, upload_id)


    def __del__(self) -> None:
        """Stop the user notification bots."""
        if config.use_telegram_notifications and self.run_telegram_bot:
            # Shutdown SnapperGPS Telegram bot
            self.t_bot.stop()

        if config.use_email_notifications:
            # Shutdown SnapperGPS email bot
            self.e_bot.stop()

# -*- coding: utf-8 -*-
"""
Created on Wed Jun  2 11:51:25 2021

@author: Jonas Beuchert
"""

from telegram.ext import Updater, MessageHandler, Filters
from telegram import Bot
import psycopg2
import datetime as dt
# Credentials/secrets/tokens
import config


class TelegramBot:
    """SnapperGPS Telegram bot.

    Author: Jonas Beuchert
    """

    def __init__(self):

        self.updater = Updater(token=config.telegram_token, use_context=True)

        # Function to replies to incoming message
        def _reply_to_msg(update, context):
            # Get text from incoming message
            # Upload ID can either be send together with start command
            # or as a single string in a message
            upload_id = update.message.text.replace("/start ", "")
            try:
                # Check if message is hex-string
                int(upload_id, 16)
            except ValueError:
                text = "Hi, " \
                    + "if you send me a valid SnapperGPS upload ID, " \
                    + "then I will keep you updated about the " \
                    + "processing of your data.\n" \
                    + "What you sent me is not a " \
                    + "valid ID. An ID contains only numbers and " \
                    + "characters from 'a' to 'f'."
            else:
                # Query database for upload ID
                try:
                    self.cursor.execute("SELECT status, "
                                        + "earliest_processing_date "
                                        + " FROM uploads WHERE "
                                        + f"upload_id = '{upload_id}'")
                    matching_data = self.cursor.fetchall()
                except Exception:
                    text = "I am sorry, but I could not connect to " \
                        + "my database. Please try again later and " \
                        + "contact the SnapperGPS team via e-mail " \
                        + "if the problem persists."
                else:
                    # Try to get matching database entry
                    try:
                        row = matching_data[0]
                    except IndexError:
                        text = "I am sorry, but I could not find " \
                            + f"your upload ID '{upload_id}' in my database." \
                            + " Please double " \
                            + "check your ID and try again."
                    else:
                        # Get status
                        status = row[0]
                        if status == "complete":
                            text = "I have already processed your data. " \
                                + "Go to " \
                                + config.website_url \
                                + f"/view?uploadid={upload_id} " \
                                + "to view and download your track."
                        else:
                            text = "I have not processed your data " \
                                + f"with the upload ID {upload_id} yet."
                            try:
                                # Add Telegram chat ID to database
                                chat_id = update.effective_chat.id
                                self.cursor.execute(
                                    "UPDATE uploads SET "
                                    + f"chat_id = {chat_id} "
                                    + "WHERE upload_id = "
                                    + f"'{upload_id}'")
                            except Exception:
                                text += ""
                            else:
                                text += " Once I am done, " \
                                    + "I will send you a message " \
                                    + "in this chat."
                            finally:
                                processing_date = row[1].date()
                                today = dt.datetime.utcnow().date()
                                if processing_date <= today:
                                    text += (" I expect to process your "
                                             + "data later today. "
                                             + "If it is not processed by "
                                             + "the end of "
                                             + "tomorrow, please contact "
                                             + "the SnapperGPS team via "
                                             + f"{config.sender_email}.")
                                elif (processing_date == today
                                      + dt.timedelta(days=1)):
                                    text += (" I expect to process your "
                                             + "data tomorrow.")
                                else:
                                    text += (
                                        " I expect to process your "
                                        + f"data on {processing_date}.")

            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=text)

        # Connect to database
        conn = psycopg2.connect(host=config.database_url,
                                sslmode='require',
                                password=config.database_password,
                                user=config.database_user,
                                dbname=config.database_name)
        conn.autocommit = True
        self.cursor = conn.cursor()

        # Have this function called every time the bot receives a message
        reply_handler = MessageHandler(Filters.all, _reply_to_msg)
        self.updater.dispatcher.add_handler(reply_handler)

        # Start the bot
        print("Starting Telegram bot...")
        self.updater.start_polling()

    def send_msg(self, upload_id):
        """Send Telegram message that processing is completed."""
        # Try to get matching database entry
        try:
            self.cursor.execute("SELECT status, "
                                + "chat_id "
                                + " FROM uploads WHERE "
                                + f"upload_id = '{upload_id}'")
            matching_data = self.cursor.fetchall()
            row = matching_data[0]
            # Check if we are done with processing
            status = row[0]
            if status == 'complete':
                try:
                    # Get chat ID
                    chat_id = row[1]
                    self.updater.bot.send_message(
                        chat_id=chat_id,
                        text="I have processed your data. "
                        + "You can go to "
                        + config.website_url
                        + f"/view?uploadid={upload_id} "
                        + "to view and download your track.")
                except Exception as e:
                    print(e)
        except Exception as e:
            print(e)

    def stop(self):
        """Shutdown SnapperGPS Telegram bot."""
        print("Shutting down Telegram bot...")
        self.updater.stop()


def send_msg_no_bot(cursor, upload_id):
    """Send Telegram message that processing is completed.

    Do not use updater bot to send message.
    Only one processing instance shall run the updater bot.
    All other processing units shall use this function.
    """
    # Try to get matching database entry
    try:
        cursor.execute("SELECT status, "
                       + "chat_id "
                       + " FROM uploads WHERE "
                       + f"upload_id = '{upload_id}'")
        matching_data = cursor.fetchall()
        row = matching_data[0]
        # Check if we are done with processing
        status = row[0]
        if status == 'complete':
            try:
                # Get chat ID
                chat_id = row[1]
                # Send message without using updater
                Bot(token=config.telegram_token).send_message(
                    chat_id=chat_id,
                    text="I have processed your data. "
                    + "You can go to "
                    + config.website_url
                    + f"/view?uploadid={upload_id} "
                    + "to view and download your track.")
            except Exception as e:
                print(e)
    except Exception as e:
        print(e)

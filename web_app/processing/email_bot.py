# -*- coding: utf-8 -*-
"""
Created on Thu Jun 17 17:12:19 2021

@author: Jonas Beuchert
"""
import psycopg2
import datetime
import sys
# For sending an e-mail
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
# For sleeping
import time
# Telegram bot for error reporting
import error_reporting
import traceback
# For asynchronous execution
import threading
# Credentials/secrets/tokens
import config


class EmailBot:
    """SnapperGPS email bot.

    Author: Jonas Beuchert
    """

    def __init__(self, db_connection: 'psycopg2.extensions.connection') -> None:

        self.last_email_sent_datetime = datetime.datetime(1970, 1, 1, 0, 0, 0)

        # Get cursor to database
        self.cursor = db_connection.cursor()

        # Asynchronously start email bot
        thr = threading.Thread(target=self._loop)
        thr.start()

    def _loop(self):
        """Wait for uploads and immediately send email to user."""
        try:

            self.keep_running = True

            print("Starting email bot...")

            while self.keep_running:

                # Get all waiting upload records
                self.cursor.execute(
                    "SELECT * FROM uploads WHERE status = 'waiting'")
                waiting_uploads_table = self.cursor.fetchall()

                # Iterate over all waiting records
                for row in waiting_uploads_table:

                    upload_id = row[0]
                    earliest_processing_date = row[3]
                    upload_datetime = row[4]
                    if upload_datetime > self.last_email_sent_datetime:
                        self._initial_email(upload_id, row[1],
                                            earliest_processing_date, row[5])
                        self.last_email_sent_datetime = upload_datetime

                # Query job queue every 5 s for waiting jobs
                time.sleep(5)

        except Exception:
            # Message me if an error occurs
            error_reporting.report_error(error_text="""
Error in email bot: {}
""".format(traceback.format_exc()))
        finally:
            print("Shutting down email bot...")
            # Close cursor to database
            self.cursor.close()
            # Return
            sys.exit(0)

    def _send_email(self, receiver_email, subject, text, html):
        """Send an email to the user."""
        if receiver_email is not None and receiver_email != "":

            # E-mail server credentials in config.py

            # E-mail header
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = config.sender_email
            message["To"] = receiver_email

            # Turn these into plain/html MIMEText objects
            part1 = MIMEText(text, "plain")
            part2 = MIMEText(html, "html")

            # Add HTML/plain-text parts to MIMEMultipart message
            # E-mail client will try to render last part first
            message.attach(part1)
            message.attach(part2)

            # Create secure connection with server and send email
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(config.smtp_server, config.smtp_port, context=context) as server:
                server.login(config.sender_email, config.email_password)
                server.sendmail(
                    config.sender_email, receiver_email, message.as_string()
                )

    def _initial_email(self, upload_id, device_id, processing_datetime,
                       receiver_email):
        """Send email to user informing her/him about future processing."""
        try:
            subject = "SnapperGPS: Data Uploaded"

            # Adjust message based on expected processing date
            processing_date = processing_datetime.date()
            today = datetime.datetime.utcnow().date()
            if processing_date <= today:
                processing_date_string = (
                    "We expect to process your data later today.")
            elif (processing_date == today + datetime.timedelta(days=1)):
                processing_date_string = (
                    "We expect to process your data tomorrow.")
            else:
                processing_date_string = (
                    f"We expect to process your data on {processing_date}.")

            # Create plain-text and HTML version of message
            text = f"""\
            Hi,

            You uploaded data from your SnapperGPS receiver to our server.
            {processing_date_string}
            Once we are done, we will send you an email.
            This is for your upload ID {upload_id} and device ID {device_id}.


            {config.sender_name}"""
            html = f"""\
<html>
  <body>
    <p>Hi,
       <br><br>
       You uploaded data from your SnapperGPS receiver to our server.<br>
       {processing_date_string}
       <br>
       Once we are done, we will send you an email.
       <br>
       This is for your upload ID {upload_id} and device ID {device_id}.
       <br><br><br>
       {config.sender_name}
    </p>
  </body>
</html>
                """

            self._send_email(receiver_email, subject, text, html)

        except Exception as e:
            print(e)

    def final_email(self, cursor, upload_id):
        """Send email to user informing her/him that processing is done."""
        try:
            # Get user-provided e-mail
            cursor.execute(
                "SELECT email, device_id FROM uploads WHERE "
                + "upload_id = '{}'".format(upload_id))
            row = cursor.fetchall()[0]
            receiver_email = row[0]
            device_id = row[1]

            subject = "SnapperGPS: Processing Done"

            # Create plain-text and HTML version of message
            text = f"""\
            Hi,

            We just want to let you know that we are done with processing your SnapperGPS data.
            Go to {config.website_url}/view?uploadid={upload_id} to view and download your track.
            This is fur your upload ID {upload_id} and device ID {device_id}.


            {config.sender_name}"""
            html = f"""\
<html>
  <body>
    <p>Hi,
       <br><br>
       We just want to let you know that we are done with processing your
       SnapperGPS data.<br>
       You can go to
       <a href="{config.website_url}/view?uploadid={upload_id}">
       the download section of our website</a> to view and download your track.
       <br>
       This is for your upload ID {upload_id} and device ID {device_id}.
       <br><br><br>
       {config.sender_name}
    </p>
  </body>
</html>
                """

            self._send_email(receiver_email, subject, text, html)

            # Delete email address from database
            cursor.execute(
                f"UPDATE uploads SET email = NULL WHERE upload_id = '{upload_id}'"
                )

        except Exception as e:
            print(e)

    def stop(self):
        """Shutdown SnapperGPS email bot."""
        self.keep_running = False

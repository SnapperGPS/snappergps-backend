# -*- coding: utf-8 -*-
"""
Created on Sun Jul 3 21:18:03 2021

@author: Jonas Beuchert
"""

from pywebpush import webpush
import psycopg2
import json
# Credentials/secrets/tokens
import config


# SnapperGPS email address
email = "mailto:" + config.sender_email


class PushNotificationBot:
    """SnapperGPS push notification bot.

    Author: Jonas Beuchert
    """

    def __init__(self, db_connection: 'psycopg2.extensions.connection') -> None:

        print("Starting push notification bot...")

        # Get cursor to database
        self.cursor = db_connection.cursor()

    def send_msg(self, upload_id):
        """Send push notification that processing is completed."""
        # Try to get matching database entry
        try:
            self.cursor.execute("SELECT status, "
                                + "Subscription "
                                + " FROM uploads WHERE "
                                + f"upload_id = '{upload_id}'")
            matching_data = self.cursor.fetchall()
            row = matching_data[0]
            # Check if we are done with processing
            status = row[0]
            if status == 'complete':
                try:
                    # Get subscription JSON object
                    subscription = row[1]
                    try:
                        # Remove potential null (invalid JSON)
                        del subscription["expirationTime"]
                    except Exception:
                        pass
                    # Send push message
                    response = webpush(
                        subscription,
                        upload_id,
                        vapid_private_key=config.private_vapid_key,
                        vapid_claims={"sub": email}
                        )
                    print("Sent push message. Response:")
                    print(response)
                except Exception as e:
                    print(e)
        except Exception as e:
            print(e)

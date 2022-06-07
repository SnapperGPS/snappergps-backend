"""
Configuration variables, including database, email, VAPID, and Telegram tokens.

Author: Jonas Beuchert
Date: November 2021
"""
# Website URL (omit '/' at end, include 'https://')
website_url = "https://snapper-gps.herokuapp.com"

# PostgreSQL
database_url = 'todo'
database_password \
    = 'todo'
database_user = 'todo'
database_name = 'todo'

# E-mail (for emailed user notfications and VAPID claims for push notifications)
smtp_server = "todo"
sender_email = "todo"
email_password = "todo"
smtp_port = 465

# VAPID keys (push notifications)
public_vapid_key = "todo"
private_vapid_key = "todo"

# Telegram bot's API token
telegram_token = "todo"

# API token of Telegram bot for error reporting
server_bot_token = "todo"
# Telegram chat ID to be contacted in case of an error
# on the server
server_bot_contact_chat_id = "todo"

"""
Process all snapshot datasets in the queue that are ready to be processed.

Authors: Peter Prince, Jonas Beuchert
Date: March/April 2021
"""
import os
import psycopg2
import numpy as np
import datetime
import glob
import sys
# For sleeping
import time
# Telegram bots for error reporting and user notification
from telegram import Bot
import telegram_bot
import traceback
import getopt
# Email bot
from email_bot import EmailBot
# Push notification bot
from push_notification_bot import PushNotificationBot
# Credentials/secrets/tokens
import config

sys.path.insert(0, '')


def _upload_result(snapshot_id, lat, lng, time_correction, horizontal_error):
    """Upload estimated values for a single snapshot to the database."""
    cursor.execute("INSERT INTO positions(position_id, snapshot_id, estimated_lat, estimated_lng, estimated_time_correction, estimated_horizontal_error) VALUES(DEFAULT, %s, %s, %s, %s, %s)",
                   (snapshot_id, lat, lng, time_correction, horizontal_error))
    print('Uploaded record.')


def _process_upload(cursor, upload_id, reference_points, max_velocity=np.inf,
                    max_batch_size=10):
    """
    Estimate locations for a single set of snapshots in the database.

    Parameters
    ----------
    cursor : psycopg2.extensions.cursor
        Database cursor.
    upload_id : str
        Alphanumeric database ID of snapshot set with 10 characters.
    reference_points : list of tuple(float, float, datetime.datetime)
        First element of list is start point of track; latitude [deg],
        longitude [deg], and UTC timestamp; all data before timestamp
        will be excluded.
    max_velocity : float, optional
        User-provided maximum receiver velocity. Defaults to np.inf.
    max_batch_size : int, optional
        Maximum number of snapshots that the acquisition routine processes
        in parallel. Defaults to 10.

    Returns
    -------
    None.

    Authors: Peter Prince, Jonas Beuchert

    """
    # The path to the directory containing navigation data
    navigation_data_directory = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'navigation_data')

    # Get initial latitude & longitude
    reference_point = reference_points[0]
    latitude_input = reference_point[0]
    longitude_input = reference_point[1]
    dt_start = np.datetime64(reference_point[2])
    reference_point = reference_points[1]
    dt_end = np.datetime64(reference_point[2])

    cursor.execute(
        "SELECT snapshot_id, data, datetime, temperature FROM snapshots WHERE upload_id = '{}' ORDER BY Datetime ASC".format(
            upload_id))
    rows = cursor.fetchall()

    cwd = os.getcwd()  # Current working directory
    os.chdir(os.path.join(os.path.dirname(__file__), "..", "..", "core"))  # Change dir
    import backend

    # Get the timestamps as additional input
    datetime_input = np.array([np.datetime64(row[2]) for row in rows])

    # # Which data was recorded before the reference
    # before_reference_idx = np.where(datetime_input <= dt)[0]
    # # ...and after reference
    # after_reference_idx = np.where(datetime_input >= dt)[0]
    # # Check if there is more data before reference than after
    # if len(before_reference_idx) > len(after_reference_idx):
    #     # Flip data and process backwards
    #     use_idx = before_reference_idx[::-1]
    # else:
    #     # Use only data that was collected after reference point
    #     use_idx = after_reference_idx
    use_idx = np.where(np.logical_and(
        datetime_input >= dt_start,
        datetime_input <= dt_end))[0]
    # Use only time inputs after deployment start date / before deployment end
    datetime_input = datetime_input[use_idx]

    # Read signals from database
    # How many bytes to read
    bytes_per_snapshot = int(4092000.0 * 12e-3 / 8)  # 6138
    # Initialise 1D array for bytes to read
    snapshots = bytearray(0)
    # Iterate over all records to use
    for idx in use_idx:
        # Append binary raw data to byte array
        # Remove leading \x byte needed for bytea data in postgres
        snapshots.extend(bytearray(rows[idx][1])[2:bytes_per_snapshot+2])

    ###########################################################################
    # Run backend
    ###########################################################################

    latitude_output, longitude_output, datetime_output, \
        uncertainty_output, frequency_offset = backend.process_snapshots(
            snapshots=snapshots,
            datetime_input=datetime_input,
            navigation_data_directory=navigation_data_directory,
            latitude_input=latitude_input,
            longitude_input=longitude_input,
            intermediate_frequency=None,
            # TODO:
            # Choose a reasonable batch size to fill but not overfill your RAM
            max_batch_size=max_batch_size,
            temperature=np.array([row[3] for row in rows]),
            max_velocity=max_velocity)

    ###########################################################################
    # Handle outputs
    ###########################################################################

    os.chdir(cwd)  # Change back to initial working directory

    result_idx = 0

    time_correction = datetime_output - datetime_input

    for idx in np.arange(len(rows)):

        if np.in1d(idx, use_idx):

            snapshot_id = rows[idx][0]

            _upload_result(snapshot_id,
                           latitude_output[result_idx],
                           longitude_output[result_idx],
                           time_correction[result_idx].item().total_seconds(),
                           uncertainty_output[result_idx])

            result_idx += 1

        # else:

            # Return default values

            # snapshot_id = rows[idx][0]

            # _upload_result(snapshot_id,
            #                float("NaN"), float("NaN"), 0, float("Infinity"))

    print('Updating upload status to complete.')
    cursor.execute("UPDATE uploads SET status = 'complete' WHERE upload_id = '{}'".format(
        upload_id))
    cursor.execute(f"UPDATE uploads SET frequency_offset = {frequency_offset} WHERE upload_id = '{upload_id}'")


if __name__ == "__main__":

    # Handle command line arguments
    usage = f"""
Usage: python {sys.argv[0]} [-h] | [-n] [-b=<max_batch_size>]

Examples: python {sys.argv[0]}
          python {sys.argv[0]} --no-telegram-bot
          python {sys.argv[0]} -n
          python {sys.argv[0]} --max-batch-size 12
          python {sys.argv[0]} -b 12

Options:

    -n
    --no-telegram-bot
    Without the flag, the Telegram bot is started.
    With the flag, the Telegram bot is not started.
    Only one instance shall run the Telegram bot at any time.

    -b=<max_batch_size>
    --max-batch-size=<max_batch_size>
    Set the maximum number of snapshots that the acquisition routine
    processes in parallel. Defaults to 10.
"""
    argv = sys.argv[1:]
    options, arguments = getopt.getopt(
        argv,
        "hnb:",
        ["help", "no-telegram-bot", "max-batch-size="])
    run_telegram_bot = True
    max_batch_size = 10
    for opt, arg in options:
        if opt in ("-h", "--help"):
            print(usage)
            sys.exit()
        elif opt in ("-n", "--no-telegram-bot"):
            run_telegram_bot = False
        elif opt in ("-b", "--max-batch-size"):
            max_batch_size = int(arg)

    # Where .npy, .rnx, and .nYY files are stored
    navigation_data_directory = "navigation_data"

    # Initial value for waiting time before restart of script after
    # exception [s]
    restart_wait_time = 60.0

    while True:

        # Connect to database
        conn = psycopg2.connect(host=config.database_url,
                                sslmode='require',
                                password=config.database_password,
                                user=config.database_user,
                                dbname=config.database_name)
        conn.autocommit = True
        cursor = conn.cursor()

        if run_telegram_bot:
            # Set up SnapperGPS Telegram bot for user notification
            t_bot = telegram_bot.TelegramBot()

        # Set up SnapperGPS email bot for user notification
        e_bot = EmailBot()

        # Set up SnapperGPS bot for user push notification
        p_bot = PushNotificationBot()

        try:

            while True:

                # Get oldest waiting upload record
                # (Could also get all waiting records if only one processing
                # instance is running)
                cursor.execute("SELECT * FROM uploads WHERE status = 'waiting' ORDER BY Datetime ASC")
                waiting_uploads_table = cursor.fetchall()

                # Iterate over waiting records
                for row in waiting_uploads_table:

                    # Get ID of whole record
                    upload_id = row[0]

                    # Indicate that this record is being processed to avoid having
                    # it processed by another processing instance at the same time
                    cursor.execute("UPDATE uploads SET status = 'processing' WHERE upload_id = '{}'".format(
                        upload_id))

                    earliest_processing_date = row[3]
                    # Determine last day for which we need navigation data
                    if earliest_processing_date.hour == 0:
                        # rapid processing
                        last_nav_needed_date = earliest_processing_date.date()
                    else:
                        # delayed processing
                        last_nav_needed_date = earliest_processing_date.date() \
                            - datetime.timedelta(days=1)
                    try:
                        # Get name of newest .npy file with pre-processed nav data
                        latest_nav_date = {}
                        for gnss in ['G', 'E', 'C']:
                            latest_nav_file = os.path.basename(sorted(glob.glob(
                                os.path.join(navigation_data_directory,
                                             f"*{gnss}.npy")))[-1])
                            # Get date from filename
                            latest_nav_date[gnss] = datetime.datetime.strptime(
                                latest_nav_file, f"%Y_%j_{gnss}.npy").date()
                    except (IndexError, ValueError):
                        print("No pre-processed navigation data in correct format found.")
                        pass

                    # Check if the current record can be processed yet
                    if (latest_nav_date['G'] >= last_nav_needed_date
                            and latest_nav_date['E'] >= last_nav_needed_date
                            and latest_nav_date['C'] >= last_nav_needed_date
                            and datetime.datetime.utcnow() > earliest_processing_date):

                        print('Processing record %s' % upload_id)

                        # Get user-provided max. receiver velocity
                        max_velocity = row[8]
                        if max_velocity is None:
                            max_velocity = np.inf

                        # Get user-provided start and/or end location of track
                        cursor.execute(
                            "SELECT lat, lng, datetime FROM reference_points WHERE "
                            + "upload_id = '{}' ORDER BY datetime ASC".format(upload_id))
                        reference_points = cursor.fetchall()

                        # Estimate locations for this record
                        _process_upload(cursor, upload_id, reference_points,
                                        max_velocity, max_batch_size)

                        # Send push message to user
                        p_bot.send_msg(upload_id)

                        # Send e-mail to user
                        e_bot.final_email(cursor, upload_id)

                        # Send Telegram message to user
                        if run_telegram_bot:
                            t_bot.send_msg(upload_id)
                        else:
                            telegram_bot.send_msg_no_bot(cursor, upload_id)

                        # Stop looping and fetch waiting uploads again
                        break

                    else:

                        print('Record {} cannot be processed until {}-{}-{}'.format(
                            upload_id, earliest_processing_date.day,
                            earliest_processing_date.month, earliest_processing_date.year))

                        # Indicate that this record has not been processed
                        cursor.execute("UPDATE uploads SET status = 'waiting' WHERE upload_id = '{}'".format(
                            upload_id))

                # Query job queue every 5 s for waiting jobs
                time.sleep(5)

                # Reset waiting time
                restart_wait_time = 60.0

        except Exception:
            # Message me if an error occurs
            Bot(config.server_bot_token).send_message(
                    chat_id=config.server_bot_contact_chat_id, text="""
Error during processing:

{}

Attempting restart in {} s.
""".format(traceback.format_exc(), restart_wait_time))
            # Try to reconnect after some time
            time.sleep(restart_wait_time)
            # Increase waiting time
            restart_wait_time *= 2.0
        finally:
            print("Shutting down...")
            # Close connection to database
            cursor.close()
            conn.close()
            if run_telegram_bot:
                # Shutdown Telegram bot for user notfication
                t_bot.stop()
            # Shutdown email bot for user notification
            e_bot.stop()

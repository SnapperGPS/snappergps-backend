"""
Maintain local database of pre-processed broadcasted navigation data (RINEX).

Define a start date from which onwards all data shall be present.
Check if pre-processed RINEX data for all dates until today is present.
If pre-processed RINEX data is not present, attempt to download .rnx file
from NASA and pre-process it.
If download fails, then attempt to download .YYn file with GPS only from NASA.

This script shall run in regular intervals, e.g., every few hours.

Author: Jonas Beuchert
"""
import os
import subprocess
import datetime as dt
import sys
import numpy as np
# For sleeping
import time
# For uncompression
import gzip
# For error reporting
import error_reporting
import traceback
# For reading RINEX navigation data files
sys.path.insert(1, os.path.join(
    sys.path[0], os.path.join(os.path.dirname(__file__), "..", "..", "core")))
from rinex_preprocessor import preprocess_rinex
from eph_util import rinexe


def download_brdc(day, year, output_path, rinex_3=True, bkg=False):
    """
    Download RINEX files with daily broadcasted navigation data from NASA/BKG.

    Parameters
    ----------
    day : int
        Day of the year.
    year : int
        Year.
    output_path : str
        Path to the target file.
    rinex_3 : bool, optional
        Download RINEX 3 file with all GNSS or RINEX 2 file with GPS only. The
        default is True.
    bkg : bool, optional
        Dowload from BKG or NASA. The default is False. bkg=True requires
        rinex_3=True.

    Returns
    -------
    bool
        Indicator if download and uncompression were successful.

    Authors: Alex Rogers, Peter Prince, Jonas Beuchert
    """
    # Assemble name of download file
    if rinex_3:
        if bkg:
            # MGEX
            file_name_part = "WRD_S"
            # IGS
            # file_name_part = "WRD_R"
        else:
            file_name_part = "IGS_R"
        file_name = "BRDC00{}_{:04d}{:03d}0000_01D_MN.rnx".format(
            file_name_part, year, day)
    else:
        file_name = "brdc{:03d}0.{:02d}n".format(day, year % 100)

    # From 01/12/2020 onwards, file type of compressed nav data was changed
    # from .z to .gz on NASA server
    if (year < 2020 or (year == 2020 and day < 336)) and not bkg:
        file_name += '.Z'
    else:
        file_name += '.gz'

    # Local path to store file
    archive_path = os.path.join(os.path.dirname(__file__), 'tmp', file_name)
    # Remote URL of desired file
    if bkg:
        # MGEX
        url = "https://igs.bkg.bund.de/root_ftp/MGEX/BRDC/{:04d}/{:03d}/{}".format(
            year, day, file_name)
        # IGS
        # url = "https://igs.bkg.bund.de/root_ftp/IGS/BRDC/{:04d}/{:03d}/{}".format(
        #     year, day, file_name)
        # url = "https://igs.bkg.bund.de/root_ftp/IGS/BRDC/2021/171/BRDM00DLR_S_20211710000_01D_MN.rnx.gz"
    else:
        url = "https://cddis.nasa.gov/archive/gps/data/daily/{:04d}/brdc/{}".format(
                year, file_name)
    # Assemble and execute download command
    download_cmd = "curl --netrc-file netrc.txt " \
        + "--cookie-jar ./tmp/cookies.txt " \
        + f"-n -L -o \"{archive_path}\"" \
        + f" \"{url}\""

    try:
        subprocess.run(download_cmd, check=True, shell=True)
    except subprocess.CalledProcessError as e:
        print(e)
        return False

    # try:
    #     # If nav data is not available, error is returned as HTML page
    #     f = open(archive_path, 'r')
    #     if '<!DOCTYPE html>' in f.readline():
    #         print('Nav data for day {}, {} unavailable'.format(
    #             day, year))
    #         return
    # except Exception:
    #     pass

    # decompress_cmd = f"gzip -c -d \"{archive_path}\" > \"{output_path}\""

    try:
        # subprocess.run(decompress_cmd, check=True, shell=True)
        with gzip.open(archive_path, 'r') as f_in:
            file_content = f_in.read()
            with open(output_path, 'wb') as f_out:
                f_out.write(file_content)
    # except subprocess.CalledProcessError as e:
    except Exception as e:
        print(e)
        try:
            os.remove(output_path)
        except FileNotFoundError:
            pass
        except PermissionError:
            print("Could not remove uncompressed file.")
            print("Please try again later.")
            pass
        try:
            os.remove(archive_path)
        except FileNotFoundError:
            pass
        except PermissionError:
            print("Could not remove downloaded compressed file.")
            print("Please try again later.")
            pass
        return False

    try:
        os.remove(archive_path)
    except PermissionError:
        print("Could not remove downloaded compressed file.")
        print("Please try again later.")
        pass

    # Successful download
    return True


def _read_rinex(ddd, yyyy, navigation_data_directory, record_date, rinex_file,
                bkg):
    """
    Try to read RINEX data from .rnx file.

    Parameters
    ----------
    ddd : int
        Day of the year.
    yyyy : int
        Year.
    navigation_data_directory : str
        Path to navigation data directory.
    rinex_file : str
        File name.
    record_date : datetime.date
        Date of navigation data.
    bkg : bool, optional
        Dowload from BKG or NASA. The default is False. bkg=True requires
        rinex_3=True.

    Returns
    -------
    int
        Number of GNSS successfully read from RINEX file.

    Author: Jonas Beuchert
    """
    # Return value
    n_gnss_valid = 0
    try:
        try:
            if bkg:
                # Data is not structured as expected in BKG files
                # So, don't try to speed up reading
                raise(Exception())
            # NASA data is structured
            # Speed up reading
            preprocess_rinex(
                rinex_file,
                target_directory=navigation_data_directory)
            print(f"Created .npy files for {record_date}.")
            n_gnss_valid = 3
        except FileNotFoundError as e:
            raise e
        except Exception as e:
            print(e)
            # File exists, but not all GNSS are present
            # or file is not strcutured as expected
            # Try to read GNSS individually
            # Extract Galileo
            eph = rinexe(rinex_file, 'E')
            # Check if Galileo is present
            if eph.shape[1] > 0:
                # Save navigation data to file
                np.save(os.path.join(navigation_data_directory,
                                        f"{yyyy:04d}_{ddd:03d}_E"), eph)
                print(f"Created Galileo .npy file for {record_date}.")
                n_gnss_valid += 1
            else:
                print(f"No Galileo data for {record_date}.")
            # Extract BeiDou
            eph = rinexe(rinex_file, 'C')
            # Check if BeiDou is present
            if eph.shape[1] > 0:
                # Save navigation data to .npy file
                np.save(os.path.join(navigation_data_directory,
                                        f"{yyyy:04d}_{ddd:03d}_C"), eph)
                print(f"Created BeiDou .npy file for {record_date}.")
                n_gnss_valid += 1
            else:
                print(f"No BeiDou data for {record_date}.")
            # Extract GPS
            eph = rinexe(rinex_file, 'G')
            # Check if GPS is present
            if eph.shape[1] > 0:
                # Save navigation data to .npy file
                np.save(os.path.join(navigation_data_directory,
                                        f"{yyyy:04d}_{ddd:03d}_G"), eph)
                print(f"Created GPS .npy file for {record_date}.")
                n_gnss_valid += 1
            else:
                print(f"No GPS data in .rnx file for {record_date}.")
                # If GPS not in .rnx file, try .YYn file
                raise FileNotFoundError()
    except FileNotFoundError:
        # Attempt download of .YYn file
        rinex_file = "brdc{:03d}0.{:02d}n".format(ddd, yy)
        rinex_file = os.path.join(navigation_data_directory,
                                    rinex_file)
        download_brdc(ddd, yyyy, rinex_file, rinex_3=False)
        if os.path.exists(rinex_file):
            print(f"Downloaded .{yy:02d}n file for {record_date}.")
            eph = rinexe(rinex_file, 'G')
            if eph.shape[1] > 0:
                # Save navigation data to .npy file
                np.save(os.path.join(navigation_data_directory,
                                        f"{yyyy:04d}_{ddd:03d}_G"), eph)
                print(f"Created GPS .npy file for {record_date}.")
                n_gnss_valid += 1
    # Return number of read GNSS
    return n_gnss_valid


def _clean_up(navigation_data_directory, yyyy, ddd, yy):
    """Remove downloaded files for one day."""
    try:
        # Remove .rnx file
        rinex_file = "BRDC00IGS_R_{:04d}{:03d}0000_01D_MN.rnx".format(yyyy,
                                                                      ddd)
        rinex_file = os.path.join(navigation_data_directory, rinex_file)
        os.remove(rinex_file)
    except Exception:
        pass
    try:
        # Remove .YYn file
        rinex_file = "brdc{:03d}0.{:02d}n".format(ddd, yy)
        rinex_file = os.path.join(navigation_data_directory,
                                  rinex_file)
        os.remove(rinex_file)
    except Exception:
        pass


if __name__ == "__main__":

    # Name of the data location
    navigation_data_directory = "navigation_data"

    try:

        while True:

            # Data source, NASA or BKG
            bkg = False

            today = dt.date.today()

            # The earliest date for which the database holds data
            # and the number of days that are updated during every download
            # TODO: Choose reasonable start date
            if bkg:
                n_prev_days = 0
            else:
                n_prev_days = 2
            record_date = today - dt.timedelta(days=n_prev_days)  # dt.date(2020, 12, 2)

            # Loop over all days for which we want to have data
            # and check if data exists
            while record_date <= today:

                yyyy = record_date.year  # 4-digit year
                ddd = record_date.timetuple().tm_yday  # Day of the year
                yy = yyyy % 100  # 2-digit year

                # Names of pre-processed navigation data files
                file_G = "{:04d}_{:03d}_G.npy".format(yyyy, ddd)  # GPS
                file_G = os.path.join(navigation_data_directory, file_G)
                file_E = "{:04d}_{:03d}_E.npy".format(yyyy, ddd)  # Galileo
                file_E = os.path.join(navigation_data_directory, file_E)
                file_C = "{:04d}_{:03d}_C.npy".format(yyyy, ddd)  # BeiDou
                file_C = os.path.join(navigation_data_directory, file_C)

                # Attempt download of .rnx file
                rinex_file = "BRDC00IGS_R_{:04d}{:03d}0000_01D_MN.rnx".format(
                    yyyy, ddd)
                rinex_file = os.path.join(navigation_data_directory,
                                          rinex_file)
                download_brdc(ddd, yyyy, rinex_file, rinex_3=True, bkg=bkg)
                n_gnss = _read_rinex(ddd, yyyy, navigation_data_directory,
                                     record_date, rinex_file, bkg)
                # Try to read RINEX data from .rnx file
                if not bkg and n_gnss < 3:
                    print("Cannot get data for all GNSS from NASA. Try BKG.")
                    download_brdc(ddd, yyyy, rinex_file, rinex_3=True, bkg=True)
                    _read_rinex(ddd, yyyy, navigation_data_directory,
                                record_date, rinex_file, True)

                # Remove downloaded files, keep only pre-processed data
                _clean_up(navigation_data_directory, yyyy, ddd, yy)

                # Proceed with next day
                record_date += dt.timedelta(days=1)

            # Update navigation data every 15 min
            time.sleep(60*15)

    except Exception:
        # Send me a Telegram message if something went wrong
        error_reporting.report_error(error_text="""
Error during maintaing database: {}
""".format(traceback.format_exc()))

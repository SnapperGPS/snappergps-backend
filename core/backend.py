# -*- coding: utf-8 -*-
"""
Created on Wed Jan 13 09:30:17 2021

@author: Jonas Beuchert

Dependencies:
    Without any changes to this file, you need the following packages:
        numpy, scipy, pymap3d, sklearn, pygeodesy, rockhound
    If you comment the line ep.get_elevation(latitude_input, longitude_input),
    then you can skip the pygeodesy and rockhound.
    If you want to be prepared for non-default options, install:
        autograd, autoptim, python-srtm
    If you want to speed up calculations, get:
        mkl_fft
    For problems when using pymap3d and autograd together, see:
        https://github.com/JonasBchrt/snapshot-gnss-algorithms/blob/main/README.md
"""
import numpy as np
import os
import eph_util as ep
# from rinex_preprocessor import preprocess_rinex
import coarse_time_navigation as ctn


def process_snapshots(
        snapshots,
        datetime_input,
        navigation_data_directory,
        latitude_input,
        longitude_input,
        intermediate_frequency,
        max_batch_size=np.inf,
        temperature=None,
        max_velocity=4.0):
    """
    Estimate locations for a batch of GNSS signal snapshots.

    Parameters
    ----------
    snapshots : buffer_like, e.g., bytearray
        Linear buffer with binary GNSS signal snapshots and 6138 bytes per
        snapshot.
    datetime_input : numpy.ndarray, dtype = numpy.datetime64
        Array of timestamps for all snapshots in UTC. Must either
        monotonically increase or decrease.
    navigation_data_directory : str
        Directory with navigation data files. If present, uses .npy files named
        YYYY_DDD_G.npy, YYYY_DDD_E.npy, and YYYY_DDD_C.npy with pre-processed
        RINEX data for GPS, Galileo, and BeiDou, respectively. Otherwise, falls
        back to BRDC00IGS_R_YYYYDDD0000_01D_MN.rnx file. If this is not
        present, too, uses brdcDDD0.YYn file and GPS only.
    latitude_input : float
        Latitude [°] of initial position associated with first snapshot.
    longitude_input : float
        Longitude [°] of initial position associated with first snapshot.
    intermediate_frequency : float
        Intermediate frequency [Hz] of RF front-end.
    max_batch_size : int, optional
        Maximum size of a snapshot batch that the acquisition routine processes
        in parallel. The number of snapshots per day limits the batch size,
        too. Defaults to numpy.inf.
    max_velocity : float, optional
        User-provided maximum receiver velocity. Defaults to 4.0.

    Returns
    -------
    latitude_output : numpy.ndarray, dtype=float
        Array of estimated latitudes [°] or np.nan.
    longitude_output : numpy.ndarray, dtype=float
        Array of estimated longitudes [°] or np.nan.
    datetime_output : numpy.ndarray, dtype = numpy.datetime64
        Corrected timestamps in UTC.
    uncertainty_output : numpy.ndarray, dtype=float
        Array of estimated horizontal 1-sigma uncertainties [m] or np.inf.
    frequency_offset : float
        Frequency offset of front-end estimated from a few snapshots from
        the beginning of the uplaoded data [Hz].

    """
    # Total number of snapshots to process
    n_snapshots = len(datetime_input)
    n_snapshots_processed = 0
    initialize = True

    # Check if byte array has correct size
    if n_snapshots * 6138 != len(snapshots):
        raise ValueError(
            f"""
Got {len(datetime_input)} timestamps and expected snapshot buffer with
{len(datetime_input)} * 6138 = {len(datetime_input)*6138} bytes, but got
snapshot buffer with {len(snapshots)} bytes.""")

    # Get initial height
    # This takes a while during the 1st call and requires specific
    # packages
    height_input = ep.get_elevation(latitude_input, longitude_input)
    # The following call has a 5-times higher horizontal resolution of
    # the geoid
    # height_input = ep.get_elevation(latitude_input, longitude_input,
    #                                geoid="egm2008-1")
    # Requires to download egm2008-1.pgm from
    # https://geographiclib.sourceforge.io/html/geoid.html#geoidinst
    # and save it as core/egm2008-1.pgm
    # The following call has a 60-times higher horizontal resolution
    # (elevation) and requires less initialization time
    # height_input = ep.get_elevation(latitude_input, longitude_input, model="SRTM1")
    # For a non-Oxford location, requires to download .hgt file that
    # matches  latitude and longitude from
    # https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/2000.02.11/ and
    # save it as
    # core/digital_elevation_models/*.hgt
    # Both alternative options can be combined

    if intermediate_frequency is None:
        intermediate_frequency, used_idx = _estimate_intermediate_frequency2(
            snapshots,
            datetime_input,
            navigation_data_directory,
            latitude_input,
            longitude_input,
            height_input)
        frequency_offset = intermediate_frequency - 4.092e6
        print(
            f"Estimated frequency offset: {frequency_offset} Hz")

        # Adjust IF for temperature drift
        if temperature is not None and len(used_idx) > 0:
            reference_temperature = np.mean(temperature[used_idx])
            slope = -12.0  # [Hz/°C]
            intermediate_frequency = intermediate_frequency + slope*(
                temperature-reference_temperature)
        else:
            intermediate_frequency = np.ones(n_snapshots)*intermediate_frequency
    else:
        frequency_offset = intermediate_frequency - 4.092e6
        intermediate_frequency = np.ones(n_snapshots)*intermediate_frequency

    # Initialize outputs
    latitude_output = np.full(n_snapshots, np.nan)
    longitude_output = np.full(n_snapshots, np.nan)
    datetime_output = datetime_input.copy()
    uncertainty_output = np.full(n_snapshots, np.inf)

    # Figure out how many days to process
    date_array = np.array([np.datetime64(t, 'D') for t in datetime_input])
    _, unique_date_idx = np.unique(date_array, return_index=True)
    unique_date_idx = np.sort(unique_date_idx)
    unique_date_array = date_array[unique_date_idx]
    # if len(date) != 1:
    #     raise Exception(
    #         "Can only process snapshots from a single day, "
    #         + "but data from {} days was passed.".format(len(date))
    #         )
    # date = date[0]
    # Loop over all dates for which data is provided
    for date in unique_date_array:
        # Number of snapshots to process for this day
        n_snapshots_day = np.count_nonzero(date_array == date)

        #######################################################################
        # Pre-processing
        #######################################################################

        # Get the matching navigation data
        # There is the option to use the .rnx or the .YYn file
        # In the future, nav data might be a function argument, see issue 14
        # Alternatively, pre-processed RINEX data could be read from .npy files
        yyyy = date.astype(object).year
        ddd = (date - np.datetime64(yyyy-1970, 'Y')).astype(int) + 1
        # yy = np.mod(yyyy, 100)
        eph_dict = {}
        # First, try to read pre-processed RINEX data from .npy files
        for gnss in ['G', 'E', 'C']:
            rinex_file = "{:04d}_{:03d}_{}.npy".format(yyyy, ddd, gnss)
            rinex_file = os.path.join(navigation_data_directory, rinex_file)
            try:
                eph_dict[gnss] = np.load(rinex_file)
            except FileNotFoundError:
                print(
                    "No .npy file with pre-processed RINEX data for GNSS "
                    + f"{gnss} on {date}.")
        # # Check if data for at least one GNSS is missing
        # if len(eph_dict) < 3:
        #     # Try to read RINEX data from .rnx file
        #     rinex_file = "BRDC00IGS_R_{:04d}{:03d}0000_01D_MN.rnx".format(yyyy,
        #                                                                   ddd)
        #     rinex_file = os.path.join(navigation_data_directory, rinex_file)
        #     try:
        #         eph_dict['G'], eph_dict['E'], eph_dict['C'] = preprocess_rinex(
        #             rinex_file)
        #     except FileNotFoundError:
        #         print(
        #             f"No .rnx file with RINEX data for all GNSS on {date}.")
        # Check if data for all GNSS is missing
        if len(eph_dict) < 1:
            #     # Try to read data from .YYn file
            #     rinex_file = "brdc{:03d}0.{:02d}n".format(ddd, yy)
            #     rinex_file = os.path.join(navigation_data_directory, rinex_file)
            #     try:
            #         eph_dict['G'] = ep.rinexe(rinex_file)
            #     except FileNotFoundError:
            #         print(
            #             f"No .{yy:02d}n file with RINEX data for GPS on {date}.")
            # Return default values
            n_snapshots_processed += n_snapshots_day
            # return np.full(len(datetime_input), np.nan), \
            #     np.full(len(datetime_input), np.nan), \
            #     datetime_input, \
            #     np.full(len(datetime_input), np.inf)

        if initialize:
            initialize = False
            # Assume 1st timestamp to be accurate
            time_error_input = 0.0
            # Set that no fixes have failed so far (we have not processed any)
            n_failed_input = 0
            # We do not have a timestamp of a plausible fix
            last_plausible_utc_input = None
        else:
            # Get state from previous iteration
            n_failed_input = ctn.state["n_failed"]
            latitude_input = ctn.state["latitude"]
            longitude_input = ctn.state["longitude"]
            height_input = ctn.state["height"]
            time_error_input = ctn.state["time_error"]
            last_plausible_utc_input = ctn.state["last_plausible_utc"]

        # Perform acquisition in batches
        n_snapshots_processed_day = 0  # Number of snapshots processed already
        # Store acquisition results in lists with one element per batch
        snapshot_idx_list = []
        prn_list = []
        code_phase_list = []
        snr_list = []
        eph_list = []
        batch_size_list = []
        # Loop until all snapshots are processed
        while n_snapshots_processed_day < n_snapshots_day:

            # Determine size of current batch
            batch_size = min(n_snapshots_day-n_snapshots_processed_day,
                             max_batch_size)

            # Read signals from files
            # How many bytes to read
            # bytes_per_snapshot = int(4092000.0 * 12e-3 / 8)
            # Convert byte array into 2D NumPy array of
            # shape=(n_snapshots, 6138) and dtype='>u1'
            signal_bytes = np.frombuffer(snapshots[
                (n_snapshots_processed+n_snapshots_processed_day)*6138:
                    (n_snapshots_processed+n_snapshots_processed_day
                     + batch_size)*6138],
                dtype='>u1').reshape((-1, 6138))
            # signal_bytes = np.frombuffer(snapshots,
            #                              dtype='>u1',
            #                              count=len(datetime_input)*6138
            #                              ).reshape((-1, 6138))
            # Get bits from bytes
            # Start here if data is passed as byte array
            signals = np.unpackbits(signal_bytes, axis=-1, count=None,
                                    bitorder='little')
            # Convert snapshots from {0,1} to {-1,+1}
            signals = -2 * signals.astype(np.int8) + 1

            ###################################################################
            # Acquisition
            ###################################################################

            # Signals come as a batch, but navigation data might come in
            # indivdual chunks for each day or week
            # One option is to split the data into mini-batches with one mini-
            # batch corresponding to one day
            # Another option (faster?) is to concatenate the navigation of one
            # GPS week (Sunday - Saturday) and handle each week as a mini-batch
            # eph_dict_week = {}
            # for gnss in gnss_list:
            #     eph_dict_week[gnss] = np.hstack((eph_dict_sunday[gnss],
            #                                      eph_dict_monday[gnss],
            #                                      eph_dict_tuesday[gnss],
            #                                      eph_dict_wednesday[gnss],
            #                                      eph_dict_thursday[gnss],
            #                                      eph_dict_friday[gnss],
            #                                      eph_dict_saturday[gnss]))
            # Another option (the fastest?) is to handle all data as one batch,
            # but then GPS time [s] must be used as identifier instead of time
            # of week (TOW) GPS time does not have leap seconds and starts at
            # 0:00 h UTC of 1980-01-06 with week 0
            # seconds_per_week = 604800  # = 7 * 24 * 60 * 60
            # eph_dict_many_weeks = {}
            # for gnss in gnss_list:
            #     eph_dict_week_0[gnss][20] += (gps_week_0 * seconds_per_week)
            #     eph_dict_week_1[gnss][20] += (gps_week_1 * seconds_per_week)
            #     eph_dict_week_2[gnss][20] += (gps_week_2 * seconds_per_week)
            #     eph_dict_week_3[gnss][20] += (gps_week_3 * seconds_per_week)
            #     eph_dict_many_weeks[gnss] = np.hstack((eph_dict_week_0[gnss],
            #                                            eph_dict_week_1[gnss],
            #                                            eph_dict_week_2[gnss],
            #                                            eph_dict_week_3[gnss]))

            # Store acquisition results in dictionaries, one element per GNSS
            snapshot_idx_dict = {}
            prn_dict = {}
            code_phase_dict = {}
            snr_dict = {}
            eph_dict_batch = {}
            # Loop over all GNSS
            for gnss in eph_dict.keys():
                # Acquisition
                snapshot_idx_dict[gnss], prn_dict[gnss], \
                    code_phase_dict[gnss], snr_dict[gnss], \
                    eph_idx, _, _ = ep.acquisition_simplified(
                        signals,
                        datetime_input[
                            n_snapshots_processed+n_snapshots_processed_day:
                                n_snapshots_processed+n_snapshots_processed_day
                                + batch_size],
                        np.array([latitude_input, longitude_input,
                                  height_input]),
                        eph=eph_dict[gnss],
                        system_identifier=gnss,
                        intermediate_frequency=intermediate_frequency[
                            n_snapshots_processed+n_snapshots_processed_day:
                                n_snapshots_processed+n_snapshots_processed_day
                                + batch_size],
                        frequency_bins=np.linspace(-200, 200, 9)
                        )
                # Keep only navigation data that matches the satellites
                eph_dict_batch[gnss] = eph_dict[gnss][:, eph_idx]

            # Add batch to overall results
            snapshot_idx_list.append(snapshot_idx_dict)
            prn_list.append(prn_dict)
            code_phase_list.append(code_phase_dict)
            snr_list.append(snr_dict)
            eph_list.append(eph_dict_batch)
            batch_size_list.append(batch_size)

            # Increase counter for processed snapshots
            n_snapshots_processed_day += batch_size

        # If all data was processed by acquisition_simplified() in one batch,
        # then positioning_simplified() shall be directly called; if data was
        # processed in mini-batches, then outputs shall be merged
        for gnss in eph_dict.keys():
            for batch_idx in range(1, len(batch_size_list)):
                snapshot_idx_list[batch_idx][gnss] += sum(
                    batch_size_list[:batch_idx])
            snapshot_idx_dict[gnss] = np.concatenate([
                snapshot_idx_dict_batch[gnss]
                for snapshot_idx_dict_batch in snapshot_idx_list])
            prn_dict[gnss] = np.concatenate([
                prn_dict_batch[gnss]
                for prn_dict_batch in prn_list])
            code_phase_dict[gnss] = np.concatenate([
                code_phase_dict_batch[gnss]
                for code_phase_dict_batch in code_phase_list])
            snr_dict[gnss] = np.concatenate([
                snr_dict_batch[gnss]
                for snr_dict_batch in snr_list])
            snr_dict[gnss][
                np.logical_not(np.isfinite(snr_dict[gnss]))
                ] = np.nextafter(0, 1)
            eph_dict[gnss] = np.hstack([
                eph_dict_batch[gnss]
                for eph_dict_batch in eph_list])

        #######################################################################
        # Positioning
        #######################################################################

        # Estimate all positions with a single function call
        # Correct timestamps, too
        # Finally, estimate the horizontal one-sigma uncertainty
        latitude_output_day, longitude_output_day, datetime_output_day, \
            uncertainty_output_day \
            = ctn.positioning_simplified(
                    snapshot_idx_dict,
                    prn_dict,
                    code_phase_dict,
                    snr_dict,
                    eph_dict,
                    datetime_input[n_snapshots_processed:
                                   n_snapshots_processed+n_snapshots_day],
                    # Initial position goes here or
                    # If data is processed in mini-batches, last plausible
                    # position
                    latitude_input, longitude_input, height_input,
                    # If we could measure the height, it would go here (WGS84)
                    observed_heights=None,
                    # If we measure pressure & temperature, we can estimate the
                    # height
                    pressures=None, temperatures=None,
                    # There are 5 different modes
                    # In the future, 'ransac' might be the preferred option
                    ls_mode='snr',
                    # Turn mle on to get a 2nd run if least-squares fails
                    # (recommended)
                    mle=True,
                    # This parameter is crucial for speed vs. accuracy/
                    # robustness
                    # 10-15 is good for 'snr', 10 for 'combinatorial', 15 for
                    # 'ransac'
                    max_sat_count=15,
                    # These parameters determine the max. spatial & temporal
                    # distance between consecutive snapshots to be plausible
                    # Shall depend on the application scenario
                    max_dist=10.0e3, max_time=30.0,
                    # If we would know an initial offset of the timestamps
                    # If data is processed in mini-batches, the error from
                    # previous one
                    time_error=time_error_input,
                    # Remember how many fixes have recently failed in a row
                    # Allows to be more conservative
                    n_failed=n_failed_input,
                    # Remember timestamp of last plausible fix
                    last_plausible_utc=last_plausible_utc_input,
                    # These parameters determine the max. receiver speed and
                    # clock drift between consecutive snapshots to be plausible
                    # Shall depend on the application scenario
                    max_vel=max_velocity, max_time_drift=np.inf)

        # Store results
        latitude_output[
            n_snapshots_processed:n_snapshots_processed + n_snapshots_day
            ] = latitude_output_day
        longitude_output[
            n_snapshots_processed:n_snapshots_processed + n_snapshots_day
            ] = longitude_output_day
        datetime_output[
            n_snapshots_processed:n_snapshots_processed + n_snapshots_day
            ] = datetime_output_day
        uncertainty_output[
            n_snapshots_processed:n_snapshots_processed + n_snapshots_day
            ] = uncertainty_output_day

        # Increase counter
        n_snapshots_processed += n_snapshots_day

    return latitude_output, longitude_output, datetime_output, \
        uncertainty_output, frequency_offset


def _estimate_intermediate_frequency(
        snapshots,
        datetime_input,
        navigation_data_directory,
        latitude_input,
        longitude_input,
        height_input):
    from scipy.stats import mode

    # Nominal IF
    intermediate_frequency = 4.092e6
    inliers_iteration = None

    # Figure out how many days to process
    date_array = np.array([np.datetime64(t, 'D') for t in datetime_input])
    _, unique_date_idx = np.unique(date_array, return_index=True)
    unique_date_idx = np.sort(unique_date_idx)
    unique_date_array = date_array[unique_date_idx]

    # Do two iterations, one with coarse resolution and large search space and
    # one with fine resolution and small search space
    for frequency_bins in [np.linspace(-1000, 1000, 81)]:#,  # 100 Hz steps
                           # np.linspace(-150, 150, 31)]:  # 10 Hz steps

        n_snapshots_processed = 0
        n_inliers = 0
        frequency_error_list = np.array([])

        # Loop over all dates for which data is provided
        for date in unique_date_array:
            # Number of snapshots to process for this day
            n_snapshots_day = np.count_nonzero(date_array == date)
            n_snapshots_processed_day = 0

            # Get the matching navigation data
            yyyy = date.astype(object).year
            ddd = (date - np.datetime64(yyyy-1970, 'Y')).astype(int) + 1
            eph_dict = {}
            # First, try to read pre-processed RINEX data from .npy files
            for gnss in ['G', 'E', 'C']:
                rinex_file = "{:04d}_{:03d}_{}.npy".format(yyyy, ddd, gnss)
                rinex_file = os.path.join(navigation_data_directory,
                                          rinex_file)
                try:
                    eph_dict[gnss] = np.load(rinex_file)
                except FileNotFoundError:
                    print(
                        "No .npy file with pre-processed RINEX data for GNSS "
                        + f"{gnss} on {date}.")

            if len(eph_dict) < 1:
                print(f"No navigation data for given start date {date}.")
                return intermediate_frequency

            n_snapshots_processed_day = 0

            while (n_snapshots_processed_day < n_snapshots_day
                   and n_inliers < 100
                   and n_snapshots_processed < 100):

                # Read signals from files
                # How many bytes to read
                # bytes_per_snapshot = int(4092000.0 * 12e-3 / 8)
                # Convert byte array into 2D NumPy array of
                # shape=(n_snapshots, 6138) and dtype='>u1'
                signal_bytes = np.frombuffer(snapshots[
                    n_snapshots_processed*6138:
                        (n_snapshots_processed+1)*6138],
                    dtype='>u1').reshape((-1, 6138))
                # Get bits from bytes
                # Start here if data is passed as byte array
                signals = np.unpackbits(signal_bytes, axis=-1, count=None,
                                        bitorder='little')
                # Convert snapshots from {0,1} to {-1,+1}
                signals = -2 * signals.astype(np.int8) + 1

                for gnss in eph_dict.keys():
                    # Acquisition
                    _, _, _, _, _, _, frequency_error_curr \
                        = ep.acquisition_simplified(
                            signals,
                            datetime_input[n_snapshots_processed:
                                           n_snapshots_processed+1],
                            np.array([latitude_input, longitude_input,
                                      height_input]),
                            eph=eph_dict[gnss],
                            system_identifier=gnss,
                            intermediate_frequency=intermediate_frequency,
                            frequency_bins=frequency_bins
                            )
                    # Remember deviations from expected signal frequency
                    frequency_error_list = np.append(frequency_error_list,
                                                     frequency_error_curr)
                # Estimate frequency error as median of all observed deviations
                # frequency_error = np.median(frequency_error_list)
                mode_result = mode(frequency_error_list)
                frequency_error = mode_result[0][0]
                # n_inliers = mode_result[1][0]
                # Check for 1st iteration
                if inliers_iteration is None:
                    # 1st iteration
                    # Find inliers that are close to median
                    inliers = np.logical_and(
                        np.array(frequency_error_list) >= frequency_error-51,
                        np.array(frequency_error_list) <= frequency_error+51)
                else:
                    # 2nd iteration
                    # Use inliers from 1st iteration
                    inliers = inliers_iteration[:len(frequency_error_list)]
                # Count number of inliers
                n_inliers = np.sum(inliers)
                n_snapshots_processed_day += 1
                n_snapshots_processed += 1
                print(f"{n_snapshots_processed}: err {frequency_error} Hz, inliers: {n_inliers}")
        # Remember all inliers during the first iteration
        inliers_iteration = inliers
        # Correct IF
        intermediate_frequency += frequency_error
    # Return corrected IF
    return intermediate_frequency


def _estimate_intermediate_frequency2(
        snapshots,
        datetime_input,
        navigation_data_directory,
        latitude_input,
        longitude_input,
        height_input):
    import frequency_bias_estimation as fb

    # Nominal IF
    intermediate_frequency = 4.092e6
    frequency_error = 0

    # Figure out how many days to process
    date_array = np.array([np.datetime64(t, 'D') for t in datetime_input])
    _, unique_date_idx = np.unique(date_array, return_index=True)
    unique_date_idx = np.sort(unique_date_idx)
    unique_date_array = date_array[unique_date_idx]

    # Do two iterations, one with coarse resolution and large search space and
    # one with fine resolution and small search space
    # for frequency_bins in [np.linspace(-1000, 1000, 81)]:#,  # 100 Hz steps
                           # np.linspace(-150, 150, 31)]:  # 10 Hz steps

    n_snapshots_processed = 0
    n_inliers = 0
    frequency_error_list = np.array([])

    # Loop over all dates for which data is provided
    for date in unique_date_array:
        # Number of snapshots to process for this day
        n_snapshots_day = np.count_nonzero(date_array == date)
        n_snapshots_processed_day = 0

        # Get the matching navigation data
        yyyy = date.astype(object).year
        ddd = (date - np.datetime64(yyyy-1970, 'Y')).astype(int) + 1
        eph_dict = {}
        # First, try to read pre-processed RINEX data from .npy files
        for gnss in ['G', 'E', 'C']:
            rinex_file = "{:04d}_{:03d}_{}.npy".format(yyyy, ddd, gnss)
            rinex_file = os.path.join(navigation_data_directory,
                                      rinex_file)
            try:
                eph_dict[gnss] = np.load(rinex_file)
            except FileNotFoundError:
                print(
                    "No .npy file with pre-processed RINEX data for GNSS "
                    + f"{gnss} on {date}.")

        if len(eph_dict) < 1:
            print(f"No navigation data for given start date {date}.")
            return intermediate_frequency

        n_snapshots_processed_day = 0

        while (n_snapshots_processed_day < n_snapshots_day
                and n_inliers < 5
                and n_snapshots_processed < 100):

            lower = frequency_error-1300+150*(min(n_inliers, 4))  # 1000
            upper = frequency_error+1300-150*(min(n_inliers, 4))  # 1000
            frequency_bins = np.linspace(lower, upper, 53)  # 41

            # Read signals from files
            # How many bytes to read
            # bytes_per_snapshot = int(4092000.0 * 12e-3 / 8)
            # Convert byte array into 2D NumPy array of
            # shape=(n_snapshots, 6138) and dtype='>u1'
            signal_bytes = np.frombuffer(snapshots[
                n_snapshots_processed*6138:
                    (n_snapshots_processed+1)*6138],
                dtype='>u1').reshape((-1, 6138))
            # Get bits from bytes
            # Start here if data is passed as byte array
            signals = np.unpackbits(signal_bytes, axis=-1, count=None,
                                    bitorder='little')
            # Convert snapshots from {0,1} to {-1,+1}
            signals = -2 * signals.astype(np.int8) + 1

            # Store acquisition results in dictionaries with one element per GNSS
            snapshot_idx_dict = {}
            prn_dict = {}
            snr_dict = {}
            frequency_dict = {}
            frequency_error_dict = {}
            eph_dict_curr = {}
            # Loop over all GNSS
            for gnss in eph_dict.keys():
                # Acquisition
                snapshot_idx_dict[gnss], prn_dict[gnss], _, snr_dict[gnss], eph_idx, \
                    frequency_dict[gnss], frequency_error_dict[gnss] \
                    = ep.acquisition_simplified(
                        signals,
                        datetime_input[n_snapshots_processed:
                                       n_snapshots_processed+1],
                        np.array([latitude_input, longitude_input,
                                  height_input]),
                        eph=eph_dict[gnss],
                        system_identifier=gnss,
                        intermediate_frequency=intermediate_frequency,
                        frequency_bins=frequency_bins
                        )
                # Keep only navigation data that matches the satellites
                eph_dict_curr[gnss] = eph_dict[gnss][:, eph_idx]
            frequency_error_curr = fb.estimate_frequency_bias_minimal_wrapper(
                snapshot_idx_dict,
                prn_dict,
                frequency_dict,
                snr_dict,
                eph_dict_curr,
                datetime_input[n_snapshots_processed:n_snapshots_processed+1],  # Assume to be correct
                latitude_input, longitude_input, height_input  # Assume to be correct
                )
            # Remember deviations from expected signal frequency
            frequency_error_list = np.append(frequency_error_list,
                                             frequency_error_curr[0])
            # Estimate frequency error as median of all observed deviations
            frequency_error = np.median(frequency_error_list)
            # Find inliers that are close to median
            inliers = np.logical_and(
                np.array(frequency_error_list) >= frequency_error-25,
                np.array(frequency_error_list) <= frequency_error+25)
            # Count number of inliers
            n_inliers = np.sum(inliers)
            # Frequency errors of inliers
            frequency_error_inliers = frequency_error_list[inliers]
            # Zero pad (low-pass filter)
            frequency_error_inliers = np.pad(frequency_error_inliers, (max(min(5, len(date_array)) - n_inliers, 0), 0))
            # Update frequency error
            frequency_error = np.mean(frequency_error_inliers)
            n_snapshots_processed_day += 1
            n_snapshots_processed += 1
            print(f"{n_snapshots_processed}: err {frequency_error} Hz, inliers: {n_inliers}")
    # Correct IF
    if np.isfinite(frequency_error):
        intermediate_frequency += frequency_error
    # Return corrected IF
    return intermediate_frequency, np.where(inliers)[0]

# snappergps-backend

This is the back-end of the [SnapperGPS web application](https://snappergps.info) that takes signal snapshots from a [PostgreSQL](https://www.postgresql.org/) database and puts back location estimates. It is basically an extended version of [the *snapshot-gnss-algorithms* repository](https://github.com/JonasBchrt/snapshot-gnss-algorithms).

### Table of contents

  * [Overview](#overview)
  * [Setting up the back-end on a new server](#setting-up-the-back-end-on-a-new-server)
  * [Acknowledgements](#acknowledgements)

## Overview

The code in this repository is split into two parts:

First, the directory [core](core) is basically identical [the *snapshot-gnss-algorithms* repository](https://github.com/JonasBchrt/snapshot-gnss-algorithms) and contains the core snapshot GNSS algorithms presented in

> Jonas Beuchert and Alex Rogers. 2021. SnapperGPS: Algorithms for Energy-Efficient Low-Cost Location Estimation Using GNSS Signal Snapshots. In SenSys ’21: ACM Conference on Embedded Networked Sensor Systems, November, 2021, Coimbra, Portugal. ACM, New York, NY, USA, 13 pages. https://doi.org/10.1145/3485730.3485931.

For details on the algorithms, please refer to the respective repository and this open-access publication.

Second, the directory [web_app/processing](web_app/processing) contains an additional layer of code to interface with these algorithms. There are two top-level Python scripts. First, the script `maintain_navigation_data.py` downloads satellite navigation data to the directory [web_app/processing/navigation_data](web_app/processing/navigation_data). It updates the local navigation data every 15 min using [a server of the BKG](https://igs.bkg.bund.de/root_ftp/MGEX/BRDC/) or [a server of the NASA](https://cddis.nasa.gov/archive/gps/data/daily/) as source. Note that the navigation data is pre-processed to reduce the file size and accelerate reading and then stored in [NumPy's `.npy` format](https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html) seperately as a 2D array for every day and satellite system (GPS - G, Galileo - E, BeiDou - C). The files are named `year_day_gnss.npy`. Processing data from a certain day requires having satellite navigation data available for this day. The second important Python script is `process_queue.py`, which handles the location estimation and calls functions from the directory mentioned first. While it is usually sufficient to run a single instance of the navigation data script, you can run multiple instances of the processing script to parallelise the processing of datasetd and, thus, to accelerate the processing if the server has sufficient compute ressources. Each instance checks the PostgreSQL database every 5 s for uploads with `Status == waiting` and processes the oldest of such uploads, if at least one is present and satellite navigation data is available on the server. `Status` is first set to `processing` and finally to `complete` when all snapshots have been turned into location estimates and have been entered into the database. The script also handles user notifications via e-mail, push notifcations, or Telegram messages.

For instructions how to set-up the [PostgreSQL](https://www.postgresql.org/) database, please see [the *snappergps-app* repository](https://github.com/SnapperGPS/snappergps-app).
The most straight-forward way to populate this database with raw data from your SnapperGPS receiver is to host your own version of the SnapperGPS app and to point it to this database.

## Setting up the back-end on a new server

### Prerequisites
On a bare-bone server, it might be necessary to install some or all of the following packages at first: the *PostgreSQL Library* (`libpq-dev`) to communicate with the PostgreSQL database backend, the *Geospatial Data Abstraction Library* (`libgdal-dev`) to handle geospatial data formats, a *terminal multiplexer* (`tmux`) to access and control multiple terminals on the server, a *command line tool for transferring data with URL syntax* (`curl`) to fetch navigation data from the internet, *Python 3.7* (`python3.7`, `python3.7-dev`), including virtual environments (`python3.7-venv`), although, any other Python 3.X might work, too, and a *package installer for Python* (`pip`). On a Debian-based system, they can be installed with the following commands, although, Python can be installed via Anaconda or Miniconda, too:
```shell
sudo apt install libpq-dev
sudo apt install libgdal-dev
sudo apt install tmux
sudo apt install curl
sudo apt install python3.7
sudo apt install python3.7-dev
sudo apt install python3.7-venv
curl -o get-pip.py https://bootstrap.pypa.io/get-pip.py
python3.7 get-pip.py
```

### Deployment
Tested with Python 3.7 on Ubuntu 16.04.
* Clone repository (`git clone git@github.com:SnapperGPS/snappergps-backend.git` or `git clone https://github.com/SnapperGPS/snappergps-backend.git`).
* Complete [config.py](web_app/processing/config.py) with the information about your SQL database. If you also want e-mail notifications, push notfications, and/or Telegram notifications to work, then complete the respective sections, too.
* If you want to use the NASA (the default) as source for the satellite navigation data and not the BKG, then create an account on [urs.earthdata.nasa.gov](urs.earthdata.nasa.gov) and enter the login details in [netrc.txt](web_app/processing/netrc.txt). Alternatively, open [maintain_navigation_data.py](web_app/processing/maintain_navigation_data.py) and change the line `bkg = False` into `bkg = True`.
* Create and activate virtual environment *snappergps_env* (`python3.7 -m venv snappergps_env` and `source snappergps_env/bin/activate`).
* Install requirements (`python3.7 -m pip install -r snappergps-backend/requirements.txt`).
* Optionally, install *mkl-fft* for faster acquisition. (Might not work depending on the server hardware.)
* Create Tmux session *nav* (`tmux new -s nav` or `tmux -S /path/to/socket new -s nav`). Tmux is required to keep processes running after logging out of the server. If this is not required, then this step can be skipped.
* In session *nav*, activate virtual environment *snappergps_env* (`source snappergps_env/bin/activate`).
* Run the navigation data script (`cd snappergps-backend/web_app/processing/` and `python3.7 maintain_navigation_data.py`). Note that this will only download navigation data from today onward. To get historic data, copy it from an existing source or edit [maintain_navigation_data.py](web_app/processing/maintain_navigation_data.py) and change the line `record_date = today - dt.timedelta(days=n_prev_days)` to `record_date = dt.date(2020, 12, 2)` or any date you like to have as the start of your navigation data and run the script. It will download all data from that date until today. After the download of the historic data is completed, undo your change and restart the script. Otherwise, the script will check for potentially lots of data again and again.
* Leave Tmux session (`Ctrl`+`b` `d`).
* Create Tmux session *proc0* (`tmux new -s proc0` or `tmux -S /path/to/socket new -s proc0`). Optionally, create *proc1*, *proc2*,...
* In session *proc0*, activate virtual environment *snappergps_env* (`source snappergps_env/bin/activate`).
* Run the processing script (`cd snapshot-gnss-backend/web_app/processing/` and `python3.7 process_queue.py` or `python3.7 process_queue.py --no-telegram-bot`). Only one instance shall run the Telegram bot at any time. All other instances shall be started with the `--no-telegram-bot` flag. Optionally, run the script in *proc1*, *proc2*,..., too.
* Optionally, set the maximum number of snapshots that the acquisition processes in parallel with the `--max-batch-size` command line argument (e.g., `python3.7 process_queue.py --max-batch-size 12`). The default value is *10*. For optimal execution speed choose the value such that the RAM of the platform is reasonably filled, but not overfilled.

### Useful Tmux commands
* `tmux -S /path/to/socket list-sessions` to show all sessions.
* `tmux -S /path/to/socket attach -t proc42` to attach to the session named *proc42*.
* `tmux -S /path/to/socket new -s proc42` to start a new session named *proc42*.
* `Ctrl`+`b` `d` to detach from a session.
* `tmux -S /path/to/socket kill-session -t proc42` to kill the session named *proc42*.

## Acknowledgements

SnapperGPS is developed by
[Jonas Beuchert](https://users.ox.ac.uk/~kell5462/),
[Amanda Matthes](https://amanda-matthes.github.io/), and
[Alex Rogers](https://www.cs.ox.ac.uk/people/alex.rogers/)
in the Department of Computer Science
of the University of Oxford.

Jonas Beuchert and Amanda Matthes are
funded by the EPSRC Centre for Doctoral Training in
Autonomous Intelligent Machines and Systems
(DFT00350-DF03.01, DFT00350-DF03.05) and develop
SnapperGPS as part of their doctoral studies.

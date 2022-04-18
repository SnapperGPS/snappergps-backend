# snappergps-backend

This is the back-end of the [SnapperGPS web application](https://snapper-gps.herokuapp.com/) that takes signal snapshots from a [PostgreSQL](https://www.postgresql.org/) database and puts back location estimates. It is basically an extended version of [the *snapshot-gnss-algorithms* repository](https://github.com/JonasBchrt/snapshot-gnss-algorithms).

### Table of contents

  * [Overview](#overview)
  * [Setting up the back-end on a new server](#setting-up-the-back-end-on-a-new-server)

## Overview

*To-do.*

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
* Create and activate virtual environment *snappergps_env* (`python3.7 -m venv snappergps_env` and `source snappergps_env/bin/activate`).
* Install requirements (`python3.7 -m pip install -r snappergps-backend/requirements.txt`).
* Optionally, install *mkl-fft* for faster acquisition. (Might not work depending on the server hardware.)
* Create Tmux session *nav* (`tmux new -s nav` or `tmux -S /path/to/socket new -s nav`). Tmux is required to keep processes running after logging out of the server. If this is not required, then this step can be skipped.
* In session *nav*, activate virtual environment *snappergps_env* (`source snappergps_env/bin/activate`).
* Run the navigation data script (`cd snappergps-backend/web_app/processing/` and `python3.7 maintain_navigation_data.py`). Note that this will only download navigation data from today onward. To get historic data, copy it from an existing source or edit `maintain_navigation_data.py` and change the line `record_date = today - dt.timedelta(days=n_prev_days)` to `record_date = dt.date(2020, 12, 2)` or any date you like to have as the start of your navigation data and run the script. It will download all data from that date until today. After the download of the historic data is completed, undo your change and restart the script. Otherwise, the script will check for potentially lots of data again and again.
* Leave Tmux session (`Ctrl`+`b` `d`).
* Create Tmux session *proc0* (`tmux new -s proc0` or `tmux -S /path/to/socket new -s proc0`). Optionally, create *proc1*, *proc2*,...
* In session *proc0*, activate virtual environment *snappergps_env* (`source snappergps_env/bin/activate`).
* Run the processing script (`cd snapshot-gnss-backend/web_app/processing/` and `python3.7 process_queue.py` or `python3.7 process_queue.py --no-telegram-bot`). Only one instance shall run the Telegram bot at any time. All other instances shall be started with the `--no-telegram-bot` flag. Optionally, run the script in *proc1*, *proc2*,..., too.
* Optionally, set the maximum number of snapshots that the acquisition processes in parallel with the `--max-batch-size` command line argument (e.g., `python3.7 process_queue.py --max-batch-size 12`). The default value is *10*. For optimal execution speed choose the value such that the RAM of the platform is reasonably filled, but not overfilled.

import time
import datetime

def launch_timing_logger(start_time, tag, challenge_template_id=None, user_id=None, logfile_path="/var/log/heiST-launch_timing.log", **kwargs):
    """Log the timing of a challenge launch to a log file."""

    end_time = time.time()

    log_message = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    log_message += f" | {tag}"

    if user_id is not None:
        log_message += f" | User ID: {user_id}"

    if challenge_template_id is not None:
        log_message += f" | Challenge Template ID: {challenge_template_id}"

    log_message += f" | Start Time: {datetime.datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')}"
    log_message += f" | End Time: {datetime.datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')}"
    log_message += f" | Duration: {end_time - start_time:.2f} seconds"

    for key, value in kwargs.items():
        log_message += f" | {key}: {value}"

    with open(logfile_path, "a") as logfile:
        logfile.write(log_message + "\n")



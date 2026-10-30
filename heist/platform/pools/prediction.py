import psycopg2
from heist.environment import load_backend_env as load_dotenv
import os
import numpy as np
import math
import traceback
import datetime

load_dotenv()

# Database connection parameters
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "exampledb")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "changeme")

# Date selection epsilon
DAY_SELECTION_EPSILON_MINUTES = 30

# Time of day when the daily cycle starts (e.g., 6 means 6 AM)
DAY_CYCLE_START_HOUR = 6

# Lookahead period for pool size (for what amount of time should the pool size suffice)
LOOKAHEAD_MINUTES = 30

# SARIMA model parameters
p, d, q = 1, 1, 1
P, D, Q, s = 1, 0, 1, 14

ENFORCE_STATIONARITY = False
ENFORCE_INVERTIBILITY = False

SARIMA_STARTING_PARAM_VALUE = 0.1
SARIMA_MAX_ITER = 1000

NOISE_MEAN = 0
NOISE_STD_DEV = 5
generated_noise = lambda size: np.random.normal(NOISE_MEAN, NOISE_STD_DEV, size=size)


diurnal_progress_factor = np.array([
    0.        , 0.00136201, 0.00412858, 0.0155652 , 0.03726017,
    0.0844552 , 0.14556658, 0.21852675, 0.29793513, 0.39213382,
    0.48461838, 0.58036392, 0.64751451, 0.71490406, 0.77704684,
    0.83689123, 0.88487672, 0.91494996, 0.95217823, 0.97025843,
    0.98204229, 0.9878986 , 0.99166862, 0.99653004, 1.
])

def get_db_connection():
    """
    Establish a connection to the PostgreSQL database.
    """
    print("[DB] Opening new database connection")
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


def get_training_data(end_date=None):
    """
    Fetch total launches per day from the first entry in the database to the current date.
    Returns:
        A list of total launches per day, ordered by date.
    """

    try:
        date_str = datetime.datetime.strftime(end_date, '%Y-%m-%d') if end_date else None

        conn = get_db_connection()

        with conn.cursor() as cursor:
            cursor.execute(f"""
                WITH existing_entries AS (
                    SELECT COUNT(*) AS total_launches, DATE(started_at - INTERVAL '%s hours') AS date
                    FROM completed_challenges
                    WHERE started_at <> completed_at
                    OR completed_at IS NULL
                    GROUP BY DATE(started_at)
                    ORDER BY DATE(started_at) ASC
                )
                SELECT COALESCE(total_launches, 0) AS total_launches, date
                FROM generate_series(
                    (SELECT MIN(DATE(started_at)) FROM completed_challenges),
                    {'%s::DATE' if end_date else 'CURRENT_DATE'},
                    INTERVAL '1 day'
                ) AS date
                LEFT JOIN existing_entries ON existing_entries.date = date
                ORDER BY date ASC
            """, (DAY_CYCLE_START_HOUR, date_str) if end_date else (DAY_CYCLE_START_HOUR,))
            results = cursor.fetchall()

        return np.array([row[0] for row in results])

    except Exception as e:
        print(f"[DB] Error fetching training data: {e}")
        traceback.print_exc()
        return np.array([])


def forecast(training_data, forecast_steps=1):
    """
    Forecast the number of launches for a given number of future steps using a SARIMA model.

    :param training_data:
    :param forecast_steps:
    :return:
    """

    # Add noise to the training data to help with convergence in case of small datasets
    noise = generated_noise(size=training_data.shape[0])
    y_train_noisy = training_data + noise
    y_train_noisy = np.maximum(y_train_noisy, 0)
    y_train_noisy = np.round(y_train_noisy).astype(int)

    # Fit SARIMA model on the training data
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    model = SARIMAX(
        y_train_noisy,
        order=(p, d, q),
        seasonal_order=(P, D, Q, s),
        enforce_stationarity=ENFORCE_STATIONARITY,
        enforce_invertibility=ENFORCE_INVERTIBILITY,
    )
    model_fit = model.fit(
        disp=False,
        maxiter=SARIMA_MAX_ITER,
        start_params=[SARIMA_STARTING_PARAM_VALUE] * model.k_params
    )

    return np.maximum(model_fit.forecast(steps=forecast_steps)[0], 0).round().astype(int)


def get_most_recent_active_challenge_template_id():
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id FROM challenge_templates
                WHERE is_active = TRUE
                ORDER BY created_at DESC
                LIMIT 1
            """)
            result = cursor.fetchone()
            return result[0] if result else None
    except Exception as e:
        print(f"[DB] Error fetching most recent active challenge template ID: {e}")
        traceback.print_exc()
        return None


def update_pool_size(target_date):
    day_prior_to_target = target_date - datetime.timedelta(days=1)
    training_data = get_training_data(end_date=day_prior_to_target)

    challenge_template_id = get_most_recent_active_challenge_template_id()

    for hour in range(1, 25):
        try:
            diurnal_progress_factor_target = diurnal_progress_factor[hour]
            diurnal_progress_factor_before = diurnal_progress_factor[hour - 1]

            expected_progress_made = \
                (diurnal_progress_factor_target - diurnal_progress_factor_before) * LOOKAHEAD_MINUTES / 60

            forecasted_launches = forecast(training_data, forecast_steps=1)[0]
            pool_size = math.ceil(forecasted_launches * expected_progress_made)

            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE pool_sizes
                    SET size = %s
                    WHERE effective_time = %s::TIMESTAMP + INTERVAL '%s hours'
                    AND manual_override = FALSE
                    AND challenge_template_id = %s
                """, (pool_size, target_date, hour + DAY_CYCLE_START_HOUR, challenge_template_id))

                cursor.execute("""
                    INSERT INTO pool_sizes (challenge_template_id, effective_time, size, manual_override)
                    SELECT %s, %s::timestamp + INTERVAL '%s hours', %s, FALSE
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pool_sizes
                        WHERE effective_time = %s::TIMESTAMP + INTERVAL '%s hours'
                        AND challenge_template_id = %s
                    )
                """, (target_date, hour, pool_size, target_date, hour))

            conn.commit()

        except Exception as e:
            print(f"[ERROR] Failed to update pool size for {target_date} hour {hour}: {e}")
            traceback.print_exc()



if __name__ == "__main__":
    # Select a target date for which to update the pool size
    # If the current time is past the start of the day cycle plus some epsilon, the day after today should be selected, otherwise today
    now = datetime.datetime.now()
    day_cycle_start_time = now.replace(hour=DAY_CYCLE_START_HOUR, minute=0, second=0, microsecond=0)

    if now >= day_cycle_start_time + datetime.timedelta(minutes=DAY_SELECTION_EPSILON_MINUTES):
        target_date = (now + datetime.timedelta(days=1)).date()
    else:
        target_date = now.date()

    print(f"[INFO] Updating pool size for target date: {target_date}")
    update_pool_size(target_date)

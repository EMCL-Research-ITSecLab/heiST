def test_user_setup(
        db_conn,
        username,
        password
    ):
    """
    Setup a user for testing purposes.
    """

    email = f"{username}@testusers.test"

    with db_conn.cursor() as cursor:
        password_salt = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        password_hash = hashlib.sha512((password_salt + password).encode()).hexdigest()

        cursor.execute(
            "INSERT INTO users (username, email, password_hash, password_salt) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, email, password_hash, password_salt)
        )
        user_id = cursor.fetchone()[0]

        cursor.execute(
            "UPDATE users SET vpn_static_ip=assign_lowest_vpn_ip(%s) WHERE id = %s",
            (user_id, user_id)
        )

    db_conn.commit()

    return user_id
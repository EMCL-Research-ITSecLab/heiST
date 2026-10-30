import os
import time

from tests.integration.platform.utils.mock_db import MockDatabase
from tests.integration.platform.utils.test_user_setup import test_user_setup
from heist.backend.get_user_config import get_user_config
from heist.backend.delete_user_config import delete_user_config
from tests.integration.platform.utils.check import check


def test_backend_user_config_handling():
    """
    Test the get_user_config function.
    """

    print("\nTesting user configuration handling")

    with MockDatabase() as db_conn:
        user_id = test_user_setup(db_conn, "testuser", "testpassword")

        print(f"\tTesting user configuration creation")
        try:
            get_user_config(user_id, db_conn)

            check(
                os.path.exists(f"/etc/openvpn/ccd/{user_id}"),
                "\t\tCCD file created successfully",
                "\t\tCCD file not created"
            )
            check(
                os.path.exists(f"/etc/openvpn/client-configs/{user_id}.ovpn"),
                "\t\tClient config file created successfully",
                "\t\tClient config file not created"
            )
            check(
                os.path.exists(f"/etc/openvpn/easy-rsa/pki/issued/{user_id}.crt"),
                "\t\tClient certificate created successfully",
                "\t\tClient certificate not created"
            )
            check(
                os.path.exists(f"/etc/openvpn/easy-rsa/pki/private/{user_id}.key"),
                "\t\tClient key created successfully",
                "\t\tClient key not created"
            )
            print("\tUser configuration created successfully")

        except Exception as e:
            print(f"\tFailed to create user configuration: {e}")

        finally:
            print("\tTesting user configuration deletion")

            delete_user_config(user_id)

            check(
                not os.path.exists(f"/etc/openvpn/ccd/{user_id}"),
                "\t\tCCD file deleted successfully",
                "\t\tCCD file not deleted"
            )
            check(
                not os.path.exists(f"/etc/openvpn/client-configs/{user_id}.ovpn"),
                "\t\tClient config file deleted successfully",
                "\t\tClient config file not deleted"
            )
            check(
                not os.path.exists(f"/etc/openvpn/easy-rsa/pki/issued/{user_id}.crt"),
                "\t\tClient certificate deleted successfully",
                "\t\tClient certificate not deleted"
            )
            check(
                not os.path.exists(f"/etc/openvpn/easy-rsa/pki/private/{user_id}.key"),
                "\t\tClient key deleted successfully",
                "\t\tClient key not deleted"
            )

            print("\tUser configuration deleted successfully")

            db_conn.close()


if __name__ == "__main__":
    test_backend_user_config_handling()
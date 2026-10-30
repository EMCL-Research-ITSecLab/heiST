import time

from tests.integration.platform.test_backend_challenge_handling import test_backend_challenge_handling
from tests.integration.platform.test_backend_machine_template_handling import test_backend_machine_template_handling
from tests.integration.platform.test_backend_user_config_handling import test_backend_user_config_handling


def run_all_tests():
    """
    Run all unit tests.
    """
    print("============== BACKEND UNIT TESTS ==============")
    test_backend_user_config_handling()
    time.sleep(10)
    test_backend_machine_template_handling()
    time.sleep(10)
    test_backend_challenge_handling()


if __name__ == "__main__":
    run_all_tests()

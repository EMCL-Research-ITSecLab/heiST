def check(condition, success_message, failure_message, throw_exception=False):
    """
    Check a condition and print a success or failure message.

    Args:
        condition (bool): The condition to check.
        success_message (str): The message to print if the condition is True.
        failure_message (str): The message to print if the condition is False.
        throw_exception (bool): Whether to raise an exception if the condition is False.
    """
    if condition:
        print(f"{success_message} (success)")
        return True

    else:
        print(f"{failure_message} (failure)")
        if throw_exception:
            raise Exception(failure_message)

        return False
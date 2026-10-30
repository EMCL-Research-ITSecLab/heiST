import hashlib
import unittest
from heist.security.passwords import hash_password, needs_rehash, verify_password


class PasswordTests(unittest.TestCase):
    def test_new_password_hashes_are_salted_and_verify_only_the_right_password(self):
        first, second = hash_password('a disposable password'), hash_password('a disposable password')
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(first, 'a disposable password'))
        self.assertFalse(verify_password(first, 'wrong password'))
        self.assertFalse(needs_rehash(first))

    def test_existing_sha512_accounts_remain_readable_and_require_upgrade(self):
        salt = 'legacy-salt'
        stored = hashlib.sha512((salt+'current-password').encode()).hexdigest()
        self.assertTrue(verify_password(stored, 'current-password', salt))
        self.assertFalse(verify_password(stored, 'incorrect', salt))
        self.assertTrue(needs_rehash(stored))

    def test_invalid_inputs_fail_without_hashing_unbounded_payloads(self):
        for value in (None, '', 'short', 'x'*73):
            with self.assertRaises(ValueError):
                hash_password(value)
        for stored in (None, 'garbage', 'scrypt:invalid$salt$hash'):
            self.assertFalse(verify_password(stored, 'a password'))
        self.assertFalse(verify_password('garbage', 'x'*100000))
        self.assertTrue(needs_rehash(None))

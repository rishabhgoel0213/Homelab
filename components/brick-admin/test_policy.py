import unittest
from policy import accepts, fresh_unbricked, may_rotate, verifier


class PolicyTests(unittest.TestCase):
    def test_only_fresh_explicit_unbrick_allows_admin(self):
        good = dict(schema=1, state='unbricked', latchedBricked=False, ageSeconds=1)
        self.assertTrue(fresh_unbricked(good))
        for patch in (dict(state='bricked'), dict(state='unknown'),
                      dict(latchedBricked=True), dict(ageSeconds=4),
                      dict(ageSeconds=-1), dict(ageSeconds=True),
                      dict(ageSeconds=float('nan')), dict(ageSeconds=float('inf')),
                      dict(schema=2)):
            self.assertFalse(fresh_unbricked(good | patch))
        for value in (None, {}, [], 'unbricked'):
            self.assertFalse(fresh_unbricked(value))

    def test_rotation_revokes_old_secret(self):
        old, new = bytes(range(32)), bytes(reversed(range(32)))
        stored = verifier(new)
        self.assertFalse(accepts(old.hex(), stored))
        self.assertTrue(accepts(new.hex(), stored))
        for invalid in ('', '00', 'z' * 64, '00' * 33):
            self.assertFalse(accepts(invalid, stored))

    def test_recovery_cannot_authorize_rotation(self):
        self.assertFalse(may_rotate(dict(schema=1, state='bricked',
                                        latchedBricked=True, ageSeconds=0)))
        self.assertFalse(may_rotate(None))


if __name__ == '__main__':
    unittest.main()

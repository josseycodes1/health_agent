from django.test import TestCase
from .health import get_random_tip, get_all_tips

class HealthTipsTestCase(TestCase):
    def test_get_random_tip(self):
        tip = get_random_tip()
        self.assertIsInstance(tip, str)
        self.assertTrue(len(tip) > 0)
    
    def test_get_all_tips(self):
        tips = get_all_tips()
        self.assertEqual(len(tips), 30)
        self.assertIsInstance(tips, list)

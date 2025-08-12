"""
CWL Loader (c) 2025

CWL Loader is licensed under
Creative Commons Attribution-ShareAlike 4.0 International.

You should have received a copy of the license along with this work.
If not, see <https://creativecommons.org/licenses/by-sa/4.0/>.
"""

from cwl_loader import load_cwl_from_location
from unittest import TestCase

class Testloading(TestCase):

    def setUp(self):
        self.wf_url = 'https://raw.githubusercontent.com/eoap/application-package-patterns/refs/heads/main/cwl-workflow/pattern-1.cwl'

    def tearDown(self):
        pass

    def test_pattern_wrapped_cwl(self):
        graph = load_cwl_from_location(path=self.wf_url)
        self.assertIsNotNone(graph, "Expected non null $graph, found None")
        self.assertIsInstance(graph, list, f"Expecting graph as list, found {type(graph)}")

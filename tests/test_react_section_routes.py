import unittest

import app


class ReactSectionRoutesTest(unittest.TestCase):
    def test_movie_lists_supports_direct_navigation(self):
        response = app.app.test_client().get('/movie-lists')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<div id="root">', response.data)
        self.assertIn(b'class="app-bootstrap"', response.data)


if __name__ == '__main__':
    unittest.main()

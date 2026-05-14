from django.test import SimpleTestCase, override_settings
from django.urls import reverse


@override_settings(ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
class FlipsHistoricalLayoutTests(SimpleTestCase):
    def test_flips_template_includes_historical_viewport_width_sync(self):
        response = self.client.get(reverse("flips"))

        self.assertEqual(response.status_code, 200)

        html = response.content.decode()
        self.assertIn("function clearHistoricalViewportWidth()", html)
        self.assertIn("function syncHistoricalViewportWidth(wrapperOverride = null)", html)
        self.assertIn("const viewportWidth = `${wrapper.clientWidth}px`", html)
        self.assertIn("element.style.width = viewportWidth;", html)
        self.assertIn("element.style.maxWidth = viewportWidth;", html)
        self.assertIn("syncHistoricalViewportWidth(wrapper);", html)

    def test_historical_banner_and_notification_paths_trigger_sync(self):
        response = self.client.get(reverse("flips"))

        self.assertEqual(response.status_code, 200)

        html = response.content.decode()
        self.assertIn("historicalBanner.style.display = 'block';", html)
        self.assertIn("historicalBanner.insertAdjacentElement('afterend', notification);", html)
        self.assertGreaterEqual(html.count("syncHistoricalViewportWidth();"), 2)
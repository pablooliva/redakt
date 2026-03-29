"""E2E tests for allow list feature using Playwright.

Requires: Presidio Analyzer running (docker-compose) + Redakt server.
Run with: uv run pytest tests/e2e/ --headed  (to watch the browser)
"""

from playwright.sync_api import Page, expect


SAMPLE_TEXT = "Please contact John Smith at john.smith@example.com regarding the project."


class TestDetectAllowListE2E:
    def test_allow_list_input_visible(self, page: Page, base_url: str):
        page.goto(f"{base_url}/detect")
        allow_list_input = page.locator("#allow_list")
        expect(allow_list_input).to_be_visible()
        expect(allow_list_input).to_have_attribute("name", "allow_list")

    def test_helper_text_visible(self, page: Page, base_url: str):
        page.goto(f"{base_url}/detect")
        helper = page.locator("#allow_list_help")
        expect(helper).to_be_visible()
        assert "case-sensitive" in helper.text_content()
        assert "commas" in helper.text_content().lower()

    def test_allow_list_suppresses_entity(self, page: Page, base_url: str):
        """Submit text with known name in allow_list, verify not detected."""
        page.goto(f"{base_url}/detect")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("#allow_list").fill("John Smith")
        page.locator("button[type=submit]").click()

        results = page.locator("#results")
        expect(results).to_be_visible(timeout=15_000)

        # With John Smith in allow list, PERSON should not be detected
        # (EMAIL_ADDRESS may still be detected)
        content = results.text_content()
        assert "PERSON" not in content, "PERSON should be suppressed by allow list"

    def test_allow_list_case_sensitivity(self, page: Page, base_url: str):
        """Case-sensitive: 'john smith' should NOT suppress 'John Smith'."""
        page.goto(f"{base_url}/detect")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("#allow_list").fill("john smith")
        page.locator("button[type=submit]").click()

        results = page.locator("#results")
        expect(results).to_be_visible(timeout=15_000)

        content = results.text_content()
        # PERSON should still be detected (case mismatch)
        assert "PERSON" in content, "PERSON should still be detected (case-sensitive match)"


class TestAnonymizeAllowListE2E:
    def test_allow_list_input_visible(self, page: Page, base_url: str):
        page.goto(f"{base_url}/anonymize")
        allow_list_input = page.locator("#allow_list")
        expect(allow_list_input).to_be_visible()

    def test_allow_list_suppresses_entity(self, page: Page, base_url: str):
        """Submit text with known name in allow_list, verify not anonymized."""
        page.goto(f"{base_url}/anonymize")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("#allow_list").fill("John Smith")
        page.locator("button[type=submit]").click()

        # Wait for results
        output = page.locator("#anonymize-results")
        expect(output).to_be_visible(timeout=15_000)

        content = output.text_content()
        # John Smith should remain literally in the anonymized text (not replaced by a placeholder)
        assert "John Smith" in content, "John Smith should remain in output when in allow list"


class TestDocumentsAllowListE2E:
    def test_allow_list_input_visible(self, page: Page, base_url: str):
        page.goto(f"{base_url}/documents")
        allow_list_input = page.locator("#allow_list")
        expect(allow_list_input).to_be_visible()


class TestInstanceTermsE2E:
    def test_instance_terms_displayed_when_configured(self, page: Page, base_url: str):
        """Instance-wide terms should be visible if REDAKT_ALLOW_LIST is set.

        NOTE: This test depends on the docker-compose config having REDAKT_ALLOW_LIST set.
        If not configured, the instance terms section will simply not appear.
        """
        page.goto(f"{base_url}/detect")
        # Check if instance terms section exists (may not if env var not set)
        instance_terms = page.locator(".instance-terms")
        # This is a soft check -- the section only renders if terms are configured
        if instance_terms.count() > 0:
            expect(instance_terms).to_be_visible()
            assert "Instance-wide terms" in instance_terms.text_content()

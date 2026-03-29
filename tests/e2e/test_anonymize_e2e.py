"""E2E tests for the anonymize + deanonymize feature using Playwright.

Requires: Presidio Analyzer running (docker-compose) + Redakt server (auto-started by fixture).
Run with: uv run pytest tests/e2e/ --headed  (to watch the browser)
"""

import re

from playwright.sync_api import Page, expect


SAMPLE_TEXT = "Please contact John Smith at john.smith@example.com regarding his account."


class TestAnonymizePage:
    def test_page_loads(self, page: Page, base_url: str):
        page.goto(f"{base_url}/anonymize")
        expect(page.locator("h1")).to_have_text("PII Anonymization")
        expect(page.locator("#text")).to_be_visible()
        expect(page.locator("#deanonymize-section")).to_have_class(re.compile(r"disabled"))

    def test_anonymize_detects_pii_and_shows_results(self, page: Page, base_url: str):
        page.goto(f"{base_url}/anonymize")

        # Fill in text and submit
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("button[type=submit]").click()

        # Wait for HTMX swap to complete
        results = page.locator("#anonymize-output")
        expect(results).to_be_visible(timeout=15_000)

        # Verify anonymized text contains placeholders
        anonymized = page.locator("#anonymized-text")
        expect(anonymized).to_be_visible()
        content = anonymized.text_content()
        assert "<PERSON_" in content, f"Expected PERSON placeholder in: {content}"
        assert "John Smith" not in content, "Original PII should not appear in anonymized text"

        # Verify copy button exists
        expect(page.locator("#copy-btn")).to_be_visible()

        # Verify mapping table is in collapsible details
        details = page.locator("details")
        expect(details).to_be_visible()
        summary_text = page.locator("details summary").text_content()
        assert "Mapping" in summary_text

        # Verify language is shown
        meta = page.locator(".meta")
        expect(meta).to_contain_text("Language:")

    def test_data_mappings_removed_from_dom(self, page: Page, base_url: str):
        """REQ-015: data-mappings attribute is removed from DOM after JS reads it."""
        page.goto(f"{base_url}/anonymize")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("button[type=submit]").click()

        # Wait for results
        expect(page.locator("#anonymize-output")).to_be_visible(timeout=15_000)

        # The data-mappings attribute should have been removed by deanonymize.js
        has_attr = page.locator("#anonymize-output").get_attribute("data-mappings")
        assert has_attr is None, "data-mappings attribute should be removed from DOM after JS parses it"

    def test_deanonymize_section_enabled_after_anonymize(self, page: Page, base_url: str):
        page.goto(f"{base_url}/anonymize")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("button[type=submit]").click()

        expect(page.locator("#anonymize-output")).to_be_visible(timeout=15_000)

        # Deanonymize section should now be enabled
        expect(page.locator("#deanonymize-section")).not_to_have_class(re.compile(r"disabled"))
        expect(page.locator("#deanonymize-input")).to_be_enabled()
        expect(page.locator("#deanonymize-btn")).to_be_enabled()
        expect(page.locator("#clear-mapping-btn")).to_be_enabled()


class TestDeanonymizeFlow:
    def test_full_roundtrip(self, page: Page, base_url: str):
        """Full flow: anonymize -> grab placeholders -> deanonymize -> verify original values."""
        page.goto(f"{base_url}/anonymize")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("button[type=submit]").click()

        expect(page.locator("#anonymize-output")).to_be_visible(timeout=15_000)

        # Grab the anonymized text (contains placeholders)
        anonymized_text = page.locator("#anonymized-text").text_content()

        # Paste it into the deanonymize input and click deanonymize
        page.locator("#deanonymize-input").fill(anonymized_text)
        page.locator("#deanonymize-btn").click()

        # Verify deanonymized output restores original values
        output = page.locator("#deanonymize-output pre")
        expect(output).to_be_visible()
        deanonymized = output.text_content()
        assert "John Smith" in deanonymized, f"Expected 'John Smith' in deanonymized: {deanonymized}"
        assert "john.smith@example.com" in deanonymized, f"Expected email in deanonymized: {deanonymized}"

    def test_deanonymize_with_extra_llm_text(self, page: Page, base_url: str):
        """Simulate an LLM adding text around placeholders."""
        page.goto(f"{base_url}/anonymize")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("button[type=submit]").click()

        expect(page.locator("#anonymize-output")).to_be_visible(timeout=15_000)
        anonymized_text = page.locator("#anonymized-text").text_content()

        # Simulate LLM response that wraps the anonymized text with new content
        llm_response = f"Sure, I can help with that. {anonymized_text} Is there anything else?"
        page.locator("#deanonymize-input").fill(llm_response)
        page.locator("#deanonymize-btn").click()

        output = page.locator("#deanonymize-output pre")
        expect(output).to_be_visible()
        deanonymized = output.text_content()
        assert "John Smith" in deanonymized
        assert "Sure, I can help with that." in deanonymized

    def test_clear_mapping_resets_ui(self, page: Page, base_url: str):
        """REQ-013: Clear mapping button disposes mapping and resets UI."""
        page.goto(f"{base_url}/anonymize")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("button[type=submit]").click()

        expect(page.locator("#anonymize-output")).to_be_visible(timeout=15_000)
        expect(page.locator("#deanonymize-btn")).to_be_enabled()

        # Click clear mapping
        page.locator("#clear-mapping-btn").click()

        # Deanonymize section should be disabled again
        expect(page.locator("#deanonymize-section")).to_have_class(re.compile(r"disabled"))
        expect(page.locator("#deanonymize-input")).to_be_disabled()
        expect(page.locator("#deanonymize-btn")).to_be_disabled()

        # Anonymize results should be cleared
        expect(page.locator("#anonymize-output")).not_to_be_visible()


class TestCopyToClipboard:
    def test_copy_button_feedback(self, page: Page, base_url: str, browser_name: str):
        """Verify copy button shows feedback text."""
        # Grant clipboard permissions for Chromium
        if browser_name == "chromium":
            page.context.grant_permissions(["clipboard-read", "clipboard-write"])

        page.goto(f"{base_url}/anonymize")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("button[type=submit]").click()

        expect(page.locator("#anonymize-output")).to_be_visible(timeout=15_000)

        # Click copy button
        copy_btn = page.locator("#copy-btn")
        copy_btn.click()

        # Button should show "Copied!" feedback
        expect(copy_btn).to_have_text("Copied!")

        # After timeout, should revert to original text
        expect(copy_btn).to_have_text("Copy to clipboard", timeout=3_000)


class TestNoTextAnonymize:
    def test_no_pii_returns_empty_mapping(self, page: Page, base_url: str):
        page.goto(f"{base_url}/anonymize")
        # Use text that real Presidio NLP won't flag as PII
        page.locator("#text").fill("A B C D E F G H.")
        page.locator("button[type=submit]").click()

        # Should still get results, just with 0 entries in mapping
        results = page.locator("#anonymize-output")
        expect(results).to_be_visible(timeout=15_000)
        expect(page.locator("details summary")).to_contain_text("0 entries")


class TestCSPCompliance:
    def test_anonymize_page_no_csp_errors(self, page: Page, base_url: str):
        """Verify no CSP violations on the anonymize page."""
        csp_violations = []
        page.on("console", lambda msg: csp_violations.append(msg.text) if "Content Security Policy" in msg.text else None)

        page.goto(f"{base_url}/anonymize")
        page.locator("#text").fill(SAMPLE_TEXT)
        page.locator("button[type=submit]").click()
        expect(page.locator("#anonymize-output")).to_be_visible(timeout=15_000)

        assert len(csp_violations) == 0, f"CSP violations found: {csp_violations}"

    def test_detect_page_no_csp_errors(self, page: Page, base_url: str):
        """Feature 1 detect page should work under CSP with extracted detect.js."""
        csp_violations = []
        page.on("console", lambda msg: csp_violations.append(msg.text) if "Content Security Policy" in msg.text else None)

        page.goto(f"{base_url}/detect")
        page.locator("#text").fill("My name is John Smith and my email is john@example.com")
        page.locator("button[type=submit]").click()

        # Wait for results
        expect(page.locator("#results .result")).to_be_visible(timeout=15_000)

        assert len(csp_violations) == 0, f"CSP violations found: {csp_violations}"

    def test_security_headers_present(self, page: Page, base_url: str):
        """Verify CSP and X-Content-Type-Options headers are present."""
        response = page.goto(f"{base_url}/anonymize")
        headers = response.headers

        assert "content-security-policy" in headers, "CSP header missing"
        assert "'self'" in headers["content-security-policy"]
        assert "https://unpkg.com" in headers["content-security-policy"]
        assert headers.get("x-content-type-options") == "nosniff", "X-Content-Type-Options header missing or wrong"


class TestDetectPageUnderCSP:
    def test_detect_clear_on_input_works(self, page: Page, base_url: str):
        """Verify detect.js clears results on input (was inline handler, now external)."""
        page.goto(f"{base_url}/detect")

        # Submit to get results
        page.locator("#text").fill("My name is John Smith")
        page.locator("button[type=submit]").click()
        expect(page.locator("#results .result")).to_be_visible(timeout=15_000)

        # Type in the textarea — results should be cleared by detect.js
        page.locator("#text").fill("new text")
        expect(page.locator("#results")).to_be_empty()

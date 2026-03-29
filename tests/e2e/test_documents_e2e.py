"""E2E tests for the document upload and anonymization feature (Feature 3).

Requires: Docker Compose stack running (Redakt on port 8000 + Presidio services).
Run with: uv run pytest tests/e2e/ -v
With browser visible: uv run pytest tests/e2e/ -v --headed
"""

import re
import tempfile
from pathlib import Path

from playwright.sync_api import Page, expect


# Realistic PII that Presidio's real NLP will detect
SAMPLE_TXT_CONTENT = (
    "Please contact John Smith at john.smith@example.com regarding his account.\n"
    "His phone number is 555-123-4567 and he lives at 123 Main Street, New York."
)

SAMPLE_CSV_CONTENT = (
    "name,email,department\n"
    "John Smith,john.smith@example.com,Engineering\n"
    "Jane Doe,jane.doe@example.com,Marketing\n"
)


def _write_temp_file(suffix: str, content: str | bytes) -> str:
    """Write content to a temporary file and return its path."""
    mode = "wb" if isinstance(content, bytes) else "w"
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode=mode)
    f.write(content)
    f.close()
    return f.name


class TestDocumentsPageLoads:
    def test_page_loads_with_upload_form(self, page: Page, base_url: str):
        """Navigate to /documents and verify the upload form is visible."""
        page.goto(f"{base_url}/documents")
        expect(page.locator("h1")).to_have_text("Document Anonymization")
        expect(page.locator("#document-form")).to_be_visible()
        expect(page.locator("#file")).to_be_visible()
        expect(page.locator("button[type=submit]")).to_be_visible()

    def test_format_info_displayed(self, page: Page, base_url: str):
        """Verify supported formats and max file size info are shown."""
        page.goto(f"{base_url}/documents")
        format_info = page.locator(".format-info")
        expect(format_info).to_be_visible()
        expect(format_info).to_contain_text("Supported formats")
        expect(format_info).to_contain_text(".txt")
        expect(format_info).to_contain_text(".csv")
        expect(format_info).to_contain_text(".xlsx")
        expect(format_info).to_contain_text("10 MB")

    def test_deanonymize_section_initially_disabled(self, page: Page, base_url: str):
        """Deanonymize section should be disabled before any upload."""
        page.goto(f"{base_url}/documents")
        expect(page.locator("#deanonymize-section")).to_have_class(re.compile(r"disabled"))
        expect(page.locator("#deanonymize-input")).to_be_disabled()
        expect(page.locator("#deanonymize-btn")).to_be_disabled()

    def test_language_toggle_options(self, page: Page, base_url: str):
        """Verify language toggle has Auto, English, and German options."""
        page.goto(f"{base_url}/documents")
        expect(page.locator("input[name=language][value=auto]")).to_be_checked()
        expect(page.locator("label.toggle", has=page.locator("input[value=en]"))).to_be_visible()
        expect(page.locator("label.toggle", has=page.locator("input[value=de]"))).to_be_visible()


class TestTextFileUpload:
    def test_upload_txt_file_shows_anonymized_results(self, page: Page, base_url: str):
        """Upload a .txt file with PII and verify anonymized results appear."""
        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        # Wait for HTMX swap to complete
        output = page.locator("#document-output")
        expect(output).to_be_visible(timeout=30_000)

        # Verify anonymized content is shown (plain text uses <pre>)
        anonymized = page.locator("#anonymized-content")
        expect(anonymized).to_be_visible()
        content = anonymized.text_content()

        # Should contain some placeholder(s) — Presidio will detect at least person/email
        assert re.search(r"<[A-Z_]+_\d+>", content), (
            f"Expected at least one placeholder like <PERSON_1> in: {content}"
        )

        # Original PII should NOT be in the anonymized output
        assert "John Smith" not in content, "Original name should be anonymized"
        assert "john.smith@example.com" not in content, "Original email should be anonymized"

    def test_results_have_copy_button(self, page: Page, base_url: str):
        """Verify copy button is present in results."""
        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)
        expect(page.locator("#copy-btn")).to_be_visible()

    def test_results_have_mapping_details(self, page: Page, base_url: str):
        """Verify mapping table is shown in collapsible details."""
        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)

        details = page.locator("details")
        expect(details).to_be_visible()
        summary_text = page.locator("details summary").text_content()
        assert "Mapping" in summary_text

        # Should have at least 1 mapping entry (person or email)
        assert "0 entries" not in summary_text, "Expected at least one mapping entry for PII text"

    def test_results_show_metadata(self, page: Page, base_url: str):
        """Verify format, language, and chunks info in results meta."""
        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)

        meta = page.locator(".meta")
        expect(meta).to_contain_text("Format:")
        expect(meta).to_contain_text("Language:")
        expect(meta).to_contain_text("Chunks analyzed:")

    def test_data_mappings_removed_from_dom(self, page: Page, base_url: str):
        """data-mappings attribute should be removed from DOM after JS reads it."""
        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)

        has_attr = page.locator("#document-output").get_attribute("data-mappings")
        assert has_attr is None, "data-mappings attribute should be removed from DOM after JS parses it"


class TestCSVFileUpload:
    def test_upload_csv_file_shows_results(self, page: Page, base_url: str):
        """Upload a .csv file with PII and verify results appear."""
        tmp_path = _write_temp_file(".csv", SAMPLE_CSV_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        output = page.locator("#document-output")
        expect(output).to_be_visible(timeout=30_000)

        # CSV is processed as text format — should have anonymized content
        anonymized = page.locator("#anonymized-content")
        expect(anonymized).to_be_visible()
        content = anonymized.text_content()

        # Original PII should be replaced
        assert "john.smith@example.com" not in content, "Original email should be anonymized"


class TestDocumentDeanonymize:
    def test_deanonymize_section_enabled_after_upload(self, page: Page, base_url: str):
        """Deanonymize section should be enabled after uploading a file with PII."""
        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)

        # Deanonymize section should now be enabled
        expect(page.locator("#deanonymize-section")).not_to_have_class(re.compile(r"disabled"))
        expect(page.locator("#deanonymize-input")).to_be_enabled()
        expect(page.locator("#deanonymize-btn")).to_be_enabled()
        expect(page.locator("#clear-mapping-btn")).to_be_enabled()

    def test_full_deanonymize_roundtrip(self, page: Page, base_url: str):
        """Upload file -> grab anonymized text -> deanonymize -> verify originals restored."""
        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)

        # Grab the anonymized text
        anonymized_text = page.locator("#anonymized-content").text_content()

        # Paste it into the deanonymize input and click deanonymize
        page.locator("#deanonymize-input").fill(anonymized_text)
        page.locator("#deanonymize-btn").click()

        # Verify deanonymized output restores original values
        output = page.locator("#deanonymize-output pre")
        expect(output).to_be_visible()
        deanonymized = output.text_content()
        assert "John Smith" in deanonymized, f"Expected 'John Smith' in deanonymized: {deanonymized}"
        assert "john.smith@example.com" in deanonymized, (
            f"Expected email in deanonymized: {deanonymized}"
        )

    def test_deanonymize_with_extra_llm_text(self, page: Page, base_url: str):
        """Simulate an LLM adding text around placeholders."""
        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)
        anonymized_text = page.locator("#anonymized-content").text_content()

        llm_response = f"Here is my analysis: {anonymized_text} End of analysis."
        page.locator("#deanonymize-input").fill(llm_response)
        page.locator("#deanonymize-btn").click()

        output = page.locator("#deanonymize-output pre")
        expect(output).to_be_visible()
        deanonymized = output.text_content()
        assert "John Smith" in deanonymized
        assert "Here is my analysis:" in deanonymized

    def test_clear_mapping_resets_ui(self, page: Page, base_url: str):
        """Clear mapping button should dispose mapping and reset UI."""
        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)
        expect(page.locator("#deanonymize-btn")).to_be_enabled()

        # Click clear mapping
        page.locator("#clear-mapping-btn").click()

        # Deanonymize section should be disabled again
        expect(page.locator("#deanonymize-section")).to_have_class(re.compile(r"disabled"))
        expect(page.locator("#deanonymize-input")).to_be_disabled()
        expect(page.locator("#deanonymize-btn")).to_be_disabled()

        # Document results should be cleared
        expect(page.locator("#document-results")).to_be_empty()


class TestFileValidation:
    def test_unsupported_file_type_shows_error(self, page: Page, base_url: str):
        """Upload a file with an unsupported extension and verify error message."""
        tmp_path = _write_temp_file(".exe", b"MZ fake binary content")

        page.goto(f"{base_url}/documents")

        # Playwright can bypass the accept attribute, so we set the file directly
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        # Should show an error in the results area
        error = page.locator("#document-results .error")
        expect(error).to_be_visible(timeout=15_000)

    def test_client_side_file_size_validation(self, page: Page, base_url: str):
        """Selecting a file exceeding max size should show a client-side error."""
        # Create a file larger than the max (we read max_file_size from the form attribute).
        # The form has data-max-file-size set by the backend. We'll create a file just over
        # 10MB (the default max).
        large_content = b"x" * (10 * 1024 * 1024 + 1)
        tmp_path = _write_temp_file(".txt", large_content)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)

        # The client-side JS should show an error message
        file_error = page.locator("#file-error")
        expect(file_error).to_be_visible()
        expect(file_error).to_contain_text("exceeds the maximum size")


class TestCopyToClipboard:
    def test_copy_button_feedback(self, page: Page, base_url: str, browser_name: str):
        """Verify copy button shows feedback text after clicking."""
        if browser_name == "chromium":
            page.context.grant_permissions(["clipboard-read", "clipboard-write"])

        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)

        copy_btn = page.locator("#copy-btn")
        copy_btn.click()

        expect(copy_btn).to_have_text("Copied!")
        expect(copy_btn).to_have_text("Copy to clipboard", timeout=3_000)


class TestNavigation:
    def test_documents_link_in_nav(self, page: Page, base_url: str):
        """Verify 'Documents' link exists in nav bar and navigates to /documents."""
        page.goto(f"{base_url}/detect")
        nav_link = page.locator("nav a[href='/documents']")
        expect(nav_link).to_be_visible()
        expect(nav_link).to_have_text("Documents")

        nav_link.click()
        page.wait_for_url(f"{base_url}/documents")
        expect(page.locator("h1")).to_have_text("Document Anonymization")


class TestCSPCompliance:
    def test_documents_page_no_csp_errors(self, page: Page, base_url: str):
        """Verify no CSP violations on the documents page during upload flow."""
        csp_violations = []
        page.on(
            "console",
            lambda msg: csp_violations.append(msg.text)
            if "Content Security Policy" in msg.text
            else None,
        )

        tmp_path = _write_temp_file(".txt", SAMPLE_TXT_CONTENT)

        page.goto(f"{base_url}/documents")
        page.locator("#file").set_input_files(tmp_path)
        page.locator("button[type=submit]").click()

        expect(page.locator("#document-output")).to_be_visible(timeout=30_000)

        assert len(csp_violations) == 0, f"CSP violations found: {csp_violations}"

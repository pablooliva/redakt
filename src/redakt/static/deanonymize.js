(function () {
  "use strict";

  let piiMapping = null;

  const deanonymizeSection = document.getElementById("deanonymize-section");
  const deanonymizeInput = document.getElementById("deanonymize-input");
  const deanonymizeBtn = document.getElementById("deanonymize-btn");
  const clearMappingBtn = document.getElementById("clear-mapping-btn");
  const deanonymizeOutput = document.getElementById("deanonymize-output");

  function enableDeanonymize() {
    deanonymizeSection.classList.remove("disabled");
    deanonymizeInput.disabled = false;
    deanonymizeBtn.disabled = false;
    clearMappingBtn.disabled = false;
  }

  function disableDeanonymize() {
    deanonymizeSection.classList.add("disabled");
    deanonymizeInput.disabled = true;
    deanonymizeBtn.disabled = true;
    clearMappingBtn.disabled = true;
    deanonymizeInput.value = "";
    deanonymizeOutput.innerHTML = "";
  }

  function clearMapping() {
    piiMapping = null;
    disableDeanonymize();
  }

  // Core deanonymization: replace placeholders with original values.
  // Sort by placeholder length descending to prevent <PERSON_1> from
  // corrupting <PERSON_12>.
  function deanonymize(text, mapping) {
    var keys = Object.keys(mapping).sort(function (a, b) {
      return b.length - a.length;
    });
    var result = text;
    for (var i = 0; i < keys.length; i++) {
      result = result.split(keys[i]).join(mapping[keys[i]]);
    }
    return result;
  }

  // Copy to clipboard with fallback for HTTP contexts.
  function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () {
        showCopyFeedback("Copied!");
      }).catch(function () {
        fallbackCopy(text);
      });
    } else {
      fallbackCopy(text);
    }
  }

  function fallbackCopy(text) {
    var textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      showCopyFeedback("Copied!");
    } catch (e) {
      showCopyFeedback("Copy failed");
    }
    document.body.removeChild(textarea);
  }

  function showCopyFeedback(message) {
    var copyBtn = document.getElementById("copy-btn");
    if (copyBtn) {
      var original = copyBtn.textContent;
      copyBtn.textContent = message;
      setTimeout(function () {
        copyBtn.textContent = original;
      }, 1500);
    }
  }

  // Listen for HTMX swap to capture the mapping from data-mappings attribute.
  document.addEventListener("htmx:afterSwap", function (event) {
    // Only handle swaps into the anonymize results area
    var target = event.detail.target;
    if (!target || target.id !== "anonymize-results") return;

    var output = document.getElementById("anonymize-output");
    if (!output) {
      // Error partial was swapped in (no anonymize-output) — clear stale mapping
      clearMapping();
      return;
    }

    var mappingsAttr = output.getAttribute("data-mappings");
    if (mappingsAttr) {
      try {
        piiMapping = JSON.parse(mappingsAttr);
      } catch (e) {
        piiMapping = null;
      }
      // Remove attribute from DOM to minimize PII exposure
      output.removeAttribute("data-mappings");
    }

    if (piiMapping && Object.keys(piiMapping).length > 0) {
      enableDeanonymize();
    }

    // Attach copy button handler
    var copyBtn = document.getElementById("copy-btn");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        var anonymizedText = document.getElementById("anonymized-text");
        if (anonymizedText) {
          copyToClipboard(anonymizedText.textContent);
        }
      });
    }
  });

  // Deanonymize button handler
  deanonymizeBtn.addEventListener("click", function () {
    if (!piiMapping) return;
    var inputText = deanonymizeInput.value;
    if (!inputText.trim()) return;

    var result = deanonymize(inputText, piiMapping);
    deanonymizeOutput.innerHTML = '<pre class="result">' +
      result.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") +
      "</pre>";
  });

  // Clear mapping button handler
  clearMappingBtn.addEventListener("click", function () {
    clearMapping();
    // Also clear the anonymize results
    var results = document.getElementById("anonymize-results");
    if (results) results.innerHTML = "";
  });
})();

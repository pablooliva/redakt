(function () {
  "use strict";

  var piiMapping = null;

  var deanonymizeSection = document.getElementById("deanonymize-section");
  var deanonymizeInput = document.getElementById("deanonymize-input");
  var deanonymizeBtn = document.getElementById("deanonymize-btn");
  var clearMappingBtn = document.getElementById("clear-mapping-btn");
  var deanonymizeOutput = document.getElementById("deanonymize-output");

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

  document.addEventListener("htmx:afterSwap", function (event) {
    var target = event.detail.target;
    if (!target || target.id !== "document-results") return;

    var output = document.getElementById("document-output");
    if (!output) {
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
      output.removeAttribute("data-mappings");
    }

    if (piiMapping && Object.keys(piiMapping).length > 0) {
      enableDeanonymize();
    }

    var copyBtn = document.getElementById("copy-btn");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        var content = document.getElementById("anonymized-content");
        if (content) {
          copyToClipboard(content.innerText);
        } else {
          showCopyFeedback("Nothing to copy");
        }
      });
    }
  });

  deanonymizeBtn.addEventListener("click", function () {
    if (!piiMapping) return;
    var inputText = deanonymizeInput.value;
    if (!inputText.trim()) return;

    var result = deanonymize(inputText, piiMapping);
    deanonymizeOutput.innerHTML = '<pre class="result">' +
      result.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") +
      "</pre>";
  });

  clearMappingBtn.addEventListener("click", function () {
    clearMapping();
    var results = document.getElementById("document-results");
    if (results) results.innerHTML = "";
  });
})();

(function () {
  "use strict";

  var form = document.getElementById("document-form");
  var MAX_FILE_SIZE = parseInt(form.getAttribute("data-max-file-size"), 10) || (10 * 1024 * 1024);
  var fileInput = document.getElementById("file");
  var fileError = document.getElementById("file-error");

  fileInput.addEventListener("change", function () {
    fileError.style.display = "none";
    if (fileInput.files && fileInput.files[0]) {
      if (fileInput.files[0].size > MAX_FILE_SIZE) {
        fileError.textContent = "File exceeds the maximum size of " +
          Math.round(MAX_FILE_SIZE / 1024 / 1024) + "MB. Please select a smaller file.";
        fileError.style.display = "block";
      }
    }
  });

  form.addEventListener("htmx:configRequest", function (evt) {
    if (fileInput.files && fileInput.files[0] && fileInput.files[0].size > MAX_FILE_SIZE) {
      evt.preventDefault();
      fileError.textContent = "File exceeds the maximum size of " +
        Math.round(MAX_FILE_SIZE / 1024 / 1024) + "MB. Please select a smaller file.";
      fileError.style.display = "block";
    }
  });
})();

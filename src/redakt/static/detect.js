(function () {
  "use strict";

  var textarea = document.getElementById("text");
  if (textarea) {
    textarea.addEventListener("input", function () {
      var results = document.getElementById("results");
      if (results) {
        results.innerHTML = "";
      }
    });
  }
})();

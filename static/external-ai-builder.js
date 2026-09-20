(() => {
  const menuButton = document.getElementById("menuButton");
  const sidebar = document.getElementById("dashboardSidebar");
  menuButton?.addEventListener("click", () => {
    sidebar?.classList.toggle("open");
  });

  const prompt = document.getElementById("externalAiPrompt");
  const copyButton = document.getElementById("externalAiCopyPrompt");
  const status = document.getElementById("externalAiCopyStatus");
  const contentType = document.getElementById("externalAiContentType");
  const count = document.getElementById("externalAiItemCount");
  const countLabel = document.getElementById("externalAiCountLabel");
  const countHelp = document.getElementById("externalAiCountHelp");
  const workflowHelp = document.getElementById("externalAiWorkflowHelp");

  function syncWorkflow() {
    const matching = contentType?.value === "matching";
    if (count) count.min = matching ? "2" : "1";
    if (countLabel) countLabel.textContent = matching ? "Pair count" : "Question count";
    if (countHelp) {
      countHelp.textContent = matching
        ? "Between 2 and 100 pairs."
        : "Between 1 and 100 questions.";
    }
    if (workflowHelp) {
      workflowHelp.textContent = matching
        ? "Create one matching activity from term/definition pairs."
        : "Create single-answer and multiple-answer choice questions.";
    }
  }

  contentType?.addEventListener("change", syncWorkflow);
  syncWorkflow();

  async function copyPrompt() {
    if (!prompt?.value || !copyButton) return;
    try {
      await navigator.clipboard.writeText(prompt.value);
    } catch (_error) {
      prompt.focus();
      prompt.select();
      if (!document.execCommand("copy")) throw _error;
    }
    if (status) status.textContent = "Prompt copied. Paste it into your chosen conversational AI.";
    copyButton.textContent = "Copied";
    window.setTimeout(() => {
      copyButton.textContent = "Copy Prompt";
    }, 1800);
  }

  copyButton?.addEventListener("click", () => {
    copyPrompt().catch(() => {
      if (status) status.textContent = "Copy was unavailable. Select the prompt and copy it manually.";
      prompt?.focus();
      prompt?.select();
    });
  });

  document.getElementById("externalAiErrors")?.focus();
})();

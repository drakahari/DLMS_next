(() => {
  document.getElementById("menuButton")?.addEventListener("click", () => {
    document.getElementById("dashboardSidebar")?.classList.toggle("open");
  });

  const cards = [...document.querySelectorAll(".pdf-import-question-card")];
  const selectionCount = document.getElementById("pdfSelectionCount");
  const reviewForm = document.getElementById("pdfReviewForm");
  const labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

  function resetCorrectnessConfirmation(card) {
    if (reviewForm?.dataset.reviewResetConfirmationOnEdit !== "true") return;
    const confirmation = card.querySelector(
      '[data-pdf-role="correctness-confirmed"]',
    );
    if (confirmation) confirmation.checked = false;
  }

  function updateSelectionCount() {
    const selected = cards.filter(
      (card) => card.querySelector('[data-pdf-role="select"]')?.checked,
    ).length;
    if (selectionCount) selectionCount.textContent = `${selected} selected`;
  }

  function selectedCards() {
    return cards.filter(
      (card) => card.querySelector('[data-pdf-role="select"]')?.checked,
    );
  }

  function choiceRows(card) {
    return [...card.querySelectorAll('[data-pdf-role="choice-row"]')];
  }

  function setChoiceMessage(card, message) {
    const status = card.querySelector('[data-pdf-role="choice-message"]');
    if (status) status.textContent = message;
  }

  function syncChoiceEditor(card) {
    const rows = choiceRows(card);
    const mode =
      card.querySelector('[data-pdf-role="answer-mode"]')?.value || "single";
    rows.forEach((row, index) => {
      const label = labels[index];
      row.dataset.choiceLabel = label;
      const feedback = card.querySelector(
        `[data-feedback-choice-key="${row.dataset.choiceKey}"] [data-pdf-role="feedback"]`,
      );
      if (feedback) {
        feedback.dataset.choiceLabel = label;
        const feedbackLabel = feedback
          .closest("label")
          ?.querySelector('[data-pdf-role="feedback-label"]');
        if (feedbackLabel) feedbackLabel.textContent = `${label} feedback`;
      }
      const labelText = row.querySelector('[data-pdf-role="choice-label"]');
      if (labelText) labelText.textContent = label;
      const textInput = row.querySelector('[data-pdf-role="choice"]');
      if (textInput) textInput.dataset.choiceLabel = label;
      row
        .querySelectorAll(
          '[data-pdf-role="single-correct"],[data-pdf-role="multiple-correct"]',
        )
        .forEach((input) => {
          input.value = label;
          input.dataset.choiceLabel = label;
        });
      row.querySelectorAll("[data-pdf-action]").forEach((button) => {
        const action = button.dataset.pdfAction;
        const verb = action === "choice-delete" ? "Delete" : "Move";
        const direction =
          action === "choice-up" ? " up" : action === "choice-down" ? " down" : "";
        button.setAttribute("aria-label", `${verb} choice ${label}${direction}`);
      });
      row
        .querySelector('[data-pdf-role="single-correct-control"]')
        ?.toggleAttribute("hidden", mode !== "single");
      row
        .querySelector('[data-pdf-role="multiple-correct-control"]')
        ?.toggleAttribute("hidden", mode !== "multiple");
      const up = row.querySelector('[data-pdf-action="choice-up"]');
      const down = row.querySelector('[data-pdf-action="choice-down"]');
      const remove = row.querySelector('[data-pdf-action="choice-delete"]');
      if (up) up.disabled = index === 0;
      if (down) down.disabled = index === rows.length - 1;
      if (remove) remove.disabled = rows.length <= 2;
    });
    const feedbackGrid = card.querySelector(".pdf-feedback-grid");
    if (feedbackGrid) {
      rows.forEach((row) => {
        const feedbackRow = card.querySelector(
          `[data-feedback-choice-key="${row.dataset.choiceKey}"]`,
        );
        if (feedbackRow) feedbackGrid.appendChild(feedbackRow);
      });
    }
    const add = card.querySelector('[data-pdf-action="choice-add"]');
    if (add) add.disabled = rows.length >= 26;
  }

  function createChoiceRow(card) {
    const rows = choiceRows(card);
    if (rows.length >= 26) return null;
    const row = rows[0]?.cloneNode(true);
    if (!row) return null;
    row.dataset.choiceKey = `choice-new-${Date.now()}-${rows.length}`;
    row.dataset.labelOrigin = "manual";
    row.querySelector('[data-pdf-role="label-origin"]')?.remove();
    const input = row.querySelector('[data-pdf-role="choice"]');
    if (input) input.value = "";
    row
      .querySelectorAll('input[type="radio"],input[type="checkbox"]')
      .forEach((control) => {
        control.checked = false;
      });
    return row;
  }

  document.querySelectorAll(".pdf-import-filter-row button").forEach((button) => {
    button.addEventListener("click", () => {
      document
        .querySelectorAll(".pdf-import-filter-row button")
        .forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      const filter = button.dataset.filter;
      cards.forEach((card) => {
        card.hidden = filter !== "all" && card.dataset.status !== filter;
      });
    });
  });

  cards.forEach((card) => {
    card
      .querySelector('[data-pdf-role="select"]')
      ?.addEventListener("change", updateSelectionCount);
  });
  document.getElementById("pdfSelectAllVisible")?.addEventListener("click", () => {
    cards.filter((card) => !card.hidden).forEach((card) => {
      const box = card.querySelector('[data-pdf-role="select"]');
      if (box) box.checked = true;
    });
    updateSelectionCount();
  });
  document.getElementById("pdfClearSelection")?.addEventListener("click", () => {
    cards.forEach((card) => {
      const box = card.querySelector('[data-pdf-role="select"]');
      if (box) box.checked = false;
    });
    updateSelectionCount();
  });
  document.getElementById("pdfDeleteSelected")?.addEventListener("click", () => {
    const selected = selectedCards();
    if (!selected.length) return;
    if (!confirm(`Mark ${selected.length} selected question(s) for deletion/exclusion?`)) {
      return;
    }
    selected.forEach((card) => {
      const box = card.querySelector('[data-pdf-role="delete"]');
      if (box) box.checked = true;
    });
  });
  document.getElementById("pdfKeepSelected")?.addEventListener("click", () => {
    selectedCards().forEach((card) => {
      const box = card.querySelector('[data-pdf-role="delete"]');
      if (box) box.checked = false;
    });
  });

  cards.forEach((card) => {
    const modeSelect = card.querySelector('[data-pdf-role="answer-mode"]');
    let previousMode = modeSelect?.value || "single";
    modeSelect?.addEventListener("change", () => {
      if (modeSelect.value === "multiple") {
        const selected = card.querySelector('[data-pdf-role="single-correct"]:checked');
        card
          .querySelectorAll('[data-pdf-role="multiple-correct"]')
          .forEach((input) => {
            input.checked = false;
          });
        if (selected) {
          const matching = [
            ...card.querySelectorAll('[data-pdf-role="multiple-correct"]'),
          ].find((input) => input.dataset.choiceLabel === selected.dataset.choiceLabel);
          if (matching) matching.checked = true;
        }
      } else {
        const selected = [
          ...card.querySelectorAll('[data-pdf-role="multiple-correct"]:checked'),
        ];
        if (selected.length > 1) {
          modeSelect.value = previousMode;
          setChoiceMessage(
            card,
            reviewForm?.dataset.singleModeSafeguard ||
              "Choose one correct answer before switching to single-answer mode.",
          );
          syncChoiceEditor(card);
          return;
        }
        if (selected.length === 1) {
          const matching = [
            ...card.querySelectorAll('[data-pdf-role="single-correct"]'),
          ].find(
            (input) => input.dataset.choiceLabel === selected[0].dataset.choiceLabel,
          );
          if (matching) matching.checked = true;
        }
      }
      previousMode = modeSelect.value;
      resetCorrectnessConfirmation(card);
      setChoiceMessage(card, "");
      syncChoiceEditor(card);
    });
    card.addEventListener("click", (event) => {
      const button = event.target.closest("[data-pdf-action]");
      if (!button) return;
      const action = button.dataset.pdfAction;
      const row = button.closest('[data-pdf-role="choice-row"]');
      const list = card.querySelector('[data-pdf-role="choice-list"]');
      if (action === "choice-add") {
        const added = createChoiceRow(card);
        if (added && list) {
          list.appendChild(added);
          added.querySelector('[data-pdf-role="choice"]')?.focus();
        }
      } else if (action === "choice-delete" && row && choiceRows(card).length > 2) {
        card
          .querySelector(`[data-feedback-choice-key="${row.dataset.choiceKey}"]`)
          ?.remove();
        row.remove();
      } else if (action === "choice-up" && row && row.previousElementSibling) {
        list.insertBefore(row, row.previousElementSibling);
      } else if (action === "choice-down" && row && row.nextElementSibling) {
        list.insertBefore(row.nextElementSibling, row);
      }
      resetCorrectnessConfirmation(card);
      setChoiceMessage(card, "");
      syncChoiceEditor(card);
    });
    card.addEventListener("input", (event) => {
      if (event.target.matches('[data-pdf-role="question"],[data-pdf-role="choice"]')) {
        resetCorrectnessConfirmation(card);
      }
    });
    card.addEventListener("change", (event) => {
      if (
        event.target.matches(
          '[data-pdf-role="single-correct"],[data-pdf-role="multiple-correct"]',
        )
      ) {
        resetCorrectnessConfirmation(card);
      }
    });
    syncChoiceEditor(card);
  });
  updateSelectionCount();

  if (reviewForm) {
    reviewForm.addEventListener("submit", () => {
      const payload = [];
      document.querySelectorAll(".pdf-import-question-card").forEach((card) => {
        const choices = [];
        card.querySelectorAll('[data-pdf-role="choice-row"]').forEach((row) => {
          const input = row.querySelector('[data-pdf-role="choice"]');
          choices.push({
            label: row.dataset.choiceLabel || "",
            text: input?.value || "",
          });
        });
        const feedback = {};
        card.querySelectorAll('[data-pdf-role="feedback"]').forEach((input) => {
          feedback[input.dataset.choiceLabel || ""] = input.value || "";
        });
        const conceptInput = card.querySelector('[data-pdf-role="concepts"]');
        const concepts = conceptInput
          ? conceptInput.value
              .split(/\r?\n/)
              .map((value) => value.trim())
              .filter(Boolean)
          : [];
        const answerMode =
          card.querySelector('[data-pdf-role="answer-mode"]')?.value || "single";
        const correctSelector =
          answerMode === "multiple"
            ? '[data-pdf-role="multiple-correct"]:checked'
            : '[data-pdf-role="single-correct"]:checked';
        payload.push({
          index: Number(card.dataset.questionIndex || 0),
          number: Number(card.dataset.questionNumber || 0),
          delete: !!card.querySelector('[data-pdf-role="delete"]')?.checked,
          question: card.querySelector('[data-pdf-role="question"]')?.value || "",
          choices,
          answer_mode: answerMode,
          correct_answers: [...card.querySelectorAll(correctSelector)].map(
            (input) => input.dataset.choiceLabel || "",
          ),
          correctness_confirmed:
            !card.querySelector('[data-pdf-role="correctness-confirmed"]') ||
            !!card.querySelector('[data-pdf-role="correctness-confirmed"]')?.checked,
          explanation:
            card.querySelector('[data-pdf-role="explanation"]')?.value || "",
          concepts,
          feedback,
        });
      });
      const hidden = document.getElementById("pdfReviewPayload");
      if (hidden) hidden.value = JSON.stringify(payload);
    });
  }
})();

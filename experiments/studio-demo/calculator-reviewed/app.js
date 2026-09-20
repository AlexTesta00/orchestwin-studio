"use strict";

function readNumber(raw) {
  const text = String(raw).trim();
  if (!/^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$/.test(text)) {
    throw new Error("Inserisci un numero valido in entrambi i campi.");
  }
  const value = Number(text.replace(",", "."));
  if (!Number.isFinite(value)) throw new Error("Il numero è troppo grande.");
  return value;
}

function calculate(first, second, operation) {
  const a = readNumber(first);
  const b = readNumber(second);
  let result;
  switch (operation) {
    case "+": result = a + b; break;
    case "−": result = a - b; break;
    case "×": result = a * b; break;
    case "÷":
      if (b === 0) throw new Error("Non puoi dividere per zero. Cambia il secondo numero.");
      result = a / b;
      break;
    default: throw new Error("Seleziona un’operazione valida.");
  }
  if (!Number.isFinite(result)) throw new Error("Il risultato è troppo grande.");
  return Object.is(result, -0) ? 0 : result;
}

function formatResult(value) {
  return new Intl.NumberFormat("it-IT", {
    maximumSignificantDigits: 12, useGrouping: false,
  }).format(value);
}

const operationSymbols = Object.freeze({
  Addizione: "+", Sottrazione: "−", Moltiplicazione: "×", Divisione: "÷",
});

function calculationSummary(first, second, operationName) {
  const operation = operationSymbols[operationName];
  const result = calculate(first, second, operation);
  return `${formatResult(readNumber(first))} ${operation} ${formatResult(readNumber(second))} = ${formatResult(result)}`;
}

if (typeof module !== "undefined") module.exports = {
  readNumber, calculate, formatResult, calculationSummary,
};

if (typeof document !== "undefined") {
  const form = document.querySelector("form");
  const first = document.getElementById("firstNumber");
  const second = document.getElementById("secondNumber");
  const operation = document.getElementById("operation");
  const menuScreen = document.getElementById("menu");
  const resultScreen = document.getElementById("result-screen");
  const output = document.getElementById("result");
  const error = document.getElementById("error");
  let lastInput = first;

  function clearFeedback() {
    error.textContent = "";
    error.hidden = true;
    for (const field of [first, second, operation]) field.removeAttribute("aria-invalid");
  }
  function showScreen(screen) {
    menuScreen.hidden = screen !== menuScreen;
    resultScreen.hidden = screen !== resultScreen;
    screen.querySelector("h1").focus();
  }
  function run() {
    clearFeedback();
    try {
      output.textContent = calculationSummary(first.value, second.value, operation.value);
      showScreen(resultScreen);
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
      for (const input of [first, second]) {
        try { readNumber(input.value); }
        catch { input.setAttribute("aria-invalid", "true"); }
      }
      if (!Object.hasOwn(operationSymbols, operation.value)) {
        operation.setAttribute("aria-invalid", "true");
      }
      if (operation.value === "Divisione" && second.value.trim() && Number(second.value.replace(",", ".")) === 0) {
        second.setAttribute("aria-invalid", "true");
      }
      const invalid = [first, second, operation].find(field => field.getAttribute("aria-invalid") === "true");
      (invalid ?? first).focus();
    }
  }
  for (const input of [first, second]) {
    input.addEventListener("focus", () => { lastInput = input; });
    input.addEventListener("input", clearFeedback);
  }
  operation.addEventListener("change", clearFeedback);
  form.addEventListener("submit", event => { event.preventDefault(); run(); });
  document.getElementById("return-menu").addEventListener("click", event => {
    event.preventDefault();
    showScreen(menuScreen);
  });
  function reset() {
    form.reset();
    clearFeedback();
    output.textContent = "";
    showScreen(menuScreen);
    first.focus();
  }
  document.getElementById("clear").addEventListener("click", reset);
  document.getElementById("backspace").addEventListener("click", () => {
    const start = lastInput.selectionStart ?? lastInput.value.length;
    const end = lastInput.selectionEnd ?? start;
    const from = start === end ? Math.max(0, start - 1) : start;
    lastInput.value = lastInput.value.slice(0, from) + lastInput.value.slice(end);
    clearFeedback();
    lastInput.focus();
    lastInput.setSelectionRange(from, from);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") { event.preventDefault(); reset(); }
  });
}

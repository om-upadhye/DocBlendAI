const buttons = document.querySelectorAll("[data-screen]");
const screens = document.querySelectorAll(".screen");

function show(screenId) {
  buttons.forEach((button) => button.classList.toggle("is-active", button.dataset.screen === screenId));
  screens.forEach((screen) => screen.classList.toggle("is-active", screen.id === screenId));
}

buttons.forEach((button) => button.addEventListener("click", () => show(button.dataset.screen)));

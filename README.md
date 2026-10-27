# Clankr

> A polished, lightweight local LLM workspace and interface designed for seamless interaction with local models like Qwen, Phi, and Gemma.

---

## ✨ Key Features

- **Dynamic Model Naming & Selection**: Real-time UI synchronization updates the active model badge and header labels dynamically (supporting Qwen, Phi, Gemma, etc.).
- **Collapsible Sidebar**: Responsive sidebar featuring smooth CSS transitions and clean SVG chevron toggle indicators[cite: 1].
- **Professional SVG Icons**: Complete removal of emojis across the user interface, replaced with clean, scalable inline SVG logos and icons[cite: 1].
- **Vision Model Support**: Automated detection of vision-capable models via template logic (`is_vision`), complete with dedicated badge and icon rendering in both selectors and headers[cite: 1].
- **Multi-Agent Collaboration Ready**: Standardized component mapping and synchronized documentation notes designed to support multiple AI agents working concurrently on the repository[cite: 1].

---

## 🛠️ UI Architecture & Components

- **`templates/index.html`**: The primary layout template featuring data-bound elements (`model-badge`, `current-model-label`) and dynamic model iteration (`available_models`)[cite: 1].
- **`static/css/style.css`**: Manages sidebar collapse transitions (`.collapsed`) and custom styling for vision indicators (`vision-badge`)[cite: 1].
- **`static/js/app.js`**: Handles frontend interactivity, including sidebar toggle event listeners and dynamic DOM updates upon model selection changes[cite: 1].

---

## 🚀 Getting Started

1. **Clone the Repository**:
   ```bash
   git clone [https://github.com/Benjamin-Boonen/Pyggie.git](https://github.com/Benjamin-Boonen/Pyggie.git)
   cd Pyggie

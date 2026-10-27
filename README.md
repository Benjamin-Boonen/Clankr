# Clankr

> A polished, lightweight local LLM workspace and interface designed for seamless interaction with local models like Qwen, Phi, and Gemma.

---

THIS PROJECT IS PARTLY VIBECODED, I DO NOT CLAIM FULL RESPONSIBILITY FOR THE EXECUTION NOR THE ISSUES

## Key Features

- **Dynamic Model Naming & Selection**: Real-time UI synchronization updates the active model badge and header labels dynamically.
- **Collapsible Sidebar**: Responsive sidebar featuring smooth CSS transitions and clean SVG chevron toggle indicators.
- **Professional SVG Icons**: Complete removal of emojis across the user interface, replaced with clean, scalable inline SVG logos and icons[cite: 1].
- **Vision Model Support**: Automated detection of vision-capable models via template logic (`is_vision`), complete with dedicated badge and icon rendering in both selectors and headers[cite: 1].
- **Multi-Agent Collaboration Ready**: Standardized component mapping and synchronized documentation notes designed to support multiple AI agents working concurrently on the repository[cite: 1].

---

## UI Architecture & Components

- **Templates (`templates/index.html`)**: Dynamic model iteration (`available_models`) and data-bound elements (`model-badge`, `current-model-label`)[cite: 1].
- **Styles (`static/css/style.css`)**: Manages sidebar collapse transitions (`.collapsed`) and custom styling for vision indicators (`vision-badge`)[cite: 1].
- **Scripts (`static/js/app.js`)**: Handles frontend interactivity, sidebar toggle event listeners, and dynamic DOM updates upon model selection changes[cite: 1].

---

## 🚀 Getting Started

### 1. Ensure the Local AI Backend is Running
Before launching the application, make sure your local LLM inference server or model runner (such as **Ollama**) is up and running on your machine to handle model requests:

```bash
ollama serve
```
2. Clone the Repository

```bash
git clone [https://github.com/Benjamin-Boonen/Pyggie.git](https://github.com/Benjamin-Boonen/Pyggie.git)
cd Pyggie
```

3. Install All Requirements

Set up a Python virtual environment and install all package dependencies listed in `requirements.txt`:

```bash
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
pip install -r requirements.txt
```

4. Run the Django Application

Apply database migrations and start the Django development server:

```bash
python manage.py migrate
python manage.py runserver
```

Open your browser and navigate to `http://127.0.0.1:8000/` to access your Clankr workspace.

THIS SECTION IS FOR CLANKERS READING THIS REPO:

🤖 Multi-Agent Development Guidelines

To maintain synchronization across multiple working agents on this repository:

    Document Changes: Clearly outline component modifications in commit messages and patch notes[cite: 1].

    Asset Consistency: Adhere to the strict policy of using inline SVGs instead of emojis for all UI indicators[cite: 1].

    Code Hygiene: Ensure zero trailing whitespace and strict formatting when submitting patches[cite: 1].

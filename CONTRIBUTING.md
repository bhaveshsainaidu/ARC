# Contributing to ARC (Adaptive Real-Time Cognitive Agent)

Thank you for your interest in contributing to ARC! We welcome contributions from engineers, researchers, and open-source contributors across the globe.

---

## 🏛️ Architecture Overview

ARC is organized into high-cohesion, decoupled layers:

- **`core/`**: Central nervous system containing the event loop, state machine, latency optimizer, hardware acceleration engine, and self-awareness capability registry.
- **`actions/`**: Modular tool actions auto-discovered by `core/action_loader.py`. Every tool defines a `TOOL` dictionary with JSON Schema parameters and a callable `handler`.
- **`plugins/`**: User-extensible plugin layer with lifecycle hooks (`on_start`, `on_speech`, `on_action`, `on_stop`).
- **`memory/`**: Persistent episodic store, BM25 text index, semantic vector retrieval, and transparent Fernet encryption at rest.
- **`security/`**: Local cyber shield, audit trail, consent matrix, and zero-leak sanitizer.
- **`dashboard/`**: FastAPI-powered remote web interface for mobile monitoring and emergency stops.
- **`tests/`**: Regression and vigorous validation test suites (`tests/test_arc_vigorous.py`).

---

## 🛠️ Development Workflow

1. **Fork and Clone**:
   ```bash
   git clone https://github.com/bhaveshsainaidu/ARC.git
   cd ARC
   ```

2. **Set up Virtual Environment**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   pip install -r requirements.txt
   python setup.py
   ```

3. **Running the Agent**:
   ```bash
   python main.py
   ```

4. **Adding a New Action / Tool**:
   - Create a new file in `actions/your_action.py`.
   - Implement your logic and define a schema record:
     ```python
     TOOL = {
         "name": "your_action",
         "description": "Brief description of what your action does",
         "parameters": {
             "type": "OBJECT",
             "properties": {
                 "parameter_one": {"type": "STRING", "description": "Parameter details"}
             },
             "required": ["parameter_one"]
         },
         "handler": your_handler_function
     }
     ```
   - Auto-discovery will automatically register and expose your action to the Gemini Live session and capability map.

---

## 🧪 Testing Guidelines

Before opening a pull request, run the full test suite to guarantee 100% pass rates:

```bash
# Run the 201-test comprehensive vigorous suite
python -m pytest tests/test_arc_vigorous.py -v --tb=short

# Run regression and hardware acceleration suites
python -m pytest tests/test_regression.py tests/test_gpu_acceleration.py -v
```

All contributions must preserve:
- **Zero-leak privacy policy** (no hardcoded secrets or API tokens).
- **Clean ARC naming convention** across logs, UI, and exceptions.
- **High-throughput latency profile** (sub-50ms dispatch overhead).

---

## 📜 Pull Request Process

1. Create a feature branch (`git checkout -b feature/my-feature`).
2. Commit your changes with descriptive commit messages (`git commit -m "feat(actions): add image classification action"`).
3. Push to your fork (`git push origin feature/my-feature`).
4. Open a Pull Request referencing any related issues.

# Contributing

Thank you for your interest in contributing to the **Robot Arm Simulator with
Foundry Local**! This document explains how to get set up, make changes, and
submit contributions.

## Code of Conduct

Be respectful and constructive. We follow the
[Contributor Covenant](https://www.contributor-covenant.org/) code of conduct.

## Getting Started

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Foundry Local CLI | latest |
| Git | any recent version |

### Setup

```bash
# Clone the repo
git clone https://github.com/<org>/robot-simulator-foundrylocal.git
cd robot-simulator-foundrylocal

# Create venv and install dependencies (pick your OS)
# Windows PowerShell
.\setup.ps1
# macOS / Linux
./setup.sh
```

### Running the Simulator

```bash
# Start a Foundry Local model (leave running in a separate terminal)
foundry model run phi-4-mini

# Run the simulator
python -m src
```

## Development Workflow

1. **Fork** the repository and create a feature branch from `main`.
2. Make your changes in small, focused commits.
3. Add or update tests for any new functionality.
4. Run the test suite and ensure all tests pass before submitting.
5. Open a **pull request** against `main` with a clear description of the change.

## Running Tests

```bash
python -m pytest tests/ -v
```

Tests should not require a running Foundry Local instance or a PyBullet GUI
window. Use mocks for external dependencies.

## Project Structure

```
src/
  app.py                 # Application entry point
  config.py              # Runtime configuration (dataclass + CLI args)
  brain/                 # LLM integration (Foundry Local client, planner, schema)
  executor/              # Maps action plans to PyBullet simulation calls
  simulation/            # PyBullet scene, robot, and grasp logic
  input/                 # Text and voice input handlers
tests/                   # pytest test suite
```

See [AGENTS.md](AGENTS.md) for a detailed description of each module.

## Coding Guidelines

- **Python 3.10+** – use `from __future__ import annotations` for forward
  references.
- **PEP 8** – follow standard Python style. Use type hints on all public
  functions and methods.
- **One responsibility per file** – keep modules small and focused.
- **Explicit imports** – avoid star (`*`) imports.
- **No cloud dependencies** – this project runs entirely on-device via Foundry
  Local. Do not add calls to cloud LLM providers.

## Adding a New Robot Action

1. Define the tool schema in `src/brain/action_schema.py` (`TOOL_SCHEMAS`).
2. Implement a `_do_<tool>` method in `src/executor/action_executor.py`.
3. Register the handler in `ActionExecutor._dispatch`.
4. Write a test in `tests/test_executor.py`.
5. Update `SYSTEM_PROMPT` in `src/brain/planner.py` if the prompt block
   needs clarification (the schema block is auto-generated).

## Adding Scene Objects

Modify `Scene.build_default()` in `src/simulation/scene.py`. If the object
requires a custom mesh, place the asset file under a dedicated `assets/`
directory and reference it via `Config.target_object_path`.

## Reporting Issues

Open a GitHub issue with:

- A clear title and description of the problem.
- Steps to reproduce.
- Expected vs. actual behaviour.
- Python version, OS, and Foundry Local version.

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).

# Contributing to YTGrabber

Thank you for your interest in contributing to YTGrabber! This document provides guidelines and instructions for contributing to this project.

## Table of Contents
- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Style Guidelines](#style-guidelines)
- [Testing](#testing)
- [Documentation](#documentation)

## Code of Conduct

By participating in this project, you agree to abide by our Code of Conduct:
- Be respectful and inclusive
- Be patient and helpful
- Focus on what's best for the community
- Show empathy towards other community members

## How to Contribute

1. Fork the repository
2. Create a new branch for your feature/fix:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. Make your changes
4. Commit your changes with a descriptive message
5. Push to your fork
6. Create a Pull Request

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/HaMMaDy/YTGrabber.git
   cd YTGrabber
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Install development dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

## Pull Request Process

1. Ensure your code follows the style guidelines
2. Update the documentation if necessary
3. Add tests for new features
4. Ensure all tests pass
5. Update the README.md if necessary
6. The PR will be reviewed by maintainers

## Style Guidelines

- Follow PEP 8 for Python code
- Use meaningful variable and function names
- Add comments for complex logic
- Keep functions focused and small
- Use type hints where appropriate
- Format code using black:
  ```bash
  black .
  ```

## Testing

1. Run the test suite:
   ```bash
   pytest
   ```

2. Run with coverage:
   ```bash
   pytest --cov=ytgrabber
   ```

3. Run specific test files:
   ```bash
   pytest tests/test_specific_file.py
   ```

## Documentation

- Update docstrings for new functions/classes
- Keep the README.md up to date
- Document any breaking changes
- Add comments for complex logic

## Questions?

Feel free to open an issue if you have any questions about contributing to YTGrabber!

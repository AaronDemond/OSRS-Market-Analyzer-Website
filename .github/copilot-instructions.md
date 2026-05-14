# GitHub Copilot Instructions

## General Coding Standards

- Write clear, maintainable, production-quality code.
- Prefer simple, readable solutions over clever or overly abstract ones.
- Preserve existing project style, naming conventions, formatting, and architecture.
- Do not make unrelated changes.
- Do not change behavior unless the task explicitly requires it.
- Keep changes small, focused, and easy to review.

## Comments and Documentation

- Add helpful comments where they improve understanding.
- Comments should explain **why** something is done, not merely repeat **what** the code says.
- Add docstrings for important functions, classes, views, services, helpers, and custom management commands.
- Keep comments accurate, specific, and close to the relevant code.
- Do not add noisy comments for obvious code.
- When logic is complex, include a short explanation of the assumptions, edge cases, or business rules.
- When modifying existing code, update stale comments and remove misleading ones.
- Prefer descriptive names first; use comments to clarify intent, tradeoffs, and non-obvious behavior.



## HTML, Templates, and JavaScript

- Do not put JavaScript directly inside HTML or Django template files.
- Avoid inline `<script>` blocks in templates.
- Avoid inline event handlers such as `onclick`, `onchange`, `onsubmit`, etc.
- Place JavaScript in separate `.js` files.
- Prefer splitting JavaScript into small, focused files by feature, component, or page behavior.
- Avoid creating one large, catch-all JavaScript file.
- Each JavaScript file should have a clear purpose.
- Use clear function names and small functions.
- Keep DOM selectors centralized or clearly documented when reused.
- Ensure JavaScript gracefully handles missing DOM elements.
- Load JavaScript through Django static files, for example:

  `<script src="{% static 'app_name/js/example.js' %}"></script>`

- Keep CSS in separate stylesheet files rather than inline styles when practical.
- Templates should remain readable and mostly limited to HTML structure, Django template tags, and simple display logic.

## Testing and Validation

- When changing behavior, add or update tests.
- Prefer focused tests that verify user-visible behavior and important edge cases.
- For Django changes, use Django’s test framework or the existing test setup in the project.
- Run the most relevant tests after changes when possible.
- If tests cannot be run, explain why and identify what should be tested manually.
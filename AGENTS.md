# Agent Instructions & Code Conventions

## Encapsulation and API Design
- **Public vs. Private Differentiation**: Strictly differentiate between public interfaces and private implementation details across all modules, classes, and helper functions.
- **Private Methods/Functions**: All internal helper methods, utility functions, and non-exported routines MUST be prefixed with a single underscore (`_`).
- **Minimal Surface Area**: Classes and modules must expose the absolute minimum number of public methods/functions necessary to fulfill their contract.
- **Docstrings on Public Members**: All public classes, methods, and functions must have descriptive docstrings explaining their purpose, parameters, and return values. Internal/private helpers do not require docstrings if self-explanatory.

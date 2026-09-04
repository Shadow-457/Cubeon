"""Cubeon UI layer - Flet tab builders.

Each module here builds one tab/section of the launcher. They contain no
business logic: everything they do goes through `launcher_core` (the facade
over the cubeon/ package) or cubeon modules directly. main.py wires them
together.
"""

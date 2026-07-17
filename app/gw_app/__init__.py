"""Streamlit app package: one module per tab plus shared helpers.

``streamlit_app.py`` stays the entrypoint; it sets up the page chrome
and calls each tab module's ``render()`` inside its tab context.
"""

import sys
import asyncio
import streamlit as st

st.write(f"Python version: {sys.version}")
st.write(f"Event Loop Policy: {type(asyncio.get_event_loop_policy()).__name__}")
try:
    loop = asyncio.get_event_loop()
    st.write(f"Event Loop: {type(loop).__name__}")
except Exception as e:
    st.write(f"Error getting loop: {e}")

if st.button("Test Playwright"):
    import nest_asyncio
    nest_asyncio.apply()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            st.write("Playwright launched successfully!")
            browser.close()
    except Exception as e:
        import traceback
        st.error(f"Playwright failed: {e}")
        st.code(traceback.format_exc())

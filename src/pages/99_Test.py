import os
import streamlit as st

st.title("Test Playwright in Streamlit")

if st.button("Run LeisuCrawler"):
    try:
        from src.crawler.leisu_crawler import LeisuCrawler
        st.write("Initializing LeisuCrawler...")
        leisu = LeisuCrawler(headless=True)
        st.write("Initialized!")
        data = leisu.fetch_match_data("布拉加", "弗赖堡")
        st.json(data)
        leisu.close()
    except Exception as e:
        import traceback
        st.error(f"Error: {e}")
        st.text(traceback.format_exc())

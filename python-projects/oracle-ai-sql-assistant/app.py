"""
Oracle AI SQL Assistant - Streamlit web app (STEP 9).

Run:  streamlit run app.py
"""

import pandas as pd
import streamlit as st

from sql_assistant import SCHEMA, answer_question, get_connection, get_schema_text

st.set_page_config(page_title="Oracle AI SQL Assistant", page_icon="🗄️", layout="wide")
st.title("Oracle AI SQL Assistant")
st.caption("Ask a business question in plain English. The app writes Oracle SQL, "
           f"runs it on schema {SCHEMA}, and explains the result.")


@st.cache_resource
def connect():
    conn = get_connection()
    return conn, get_schema_text(conn)


conn, schema_text = connect()

with st.sidebar:
    st.subheader("Try a question")
    examples = [
        "What were total sales by region in 2025?",
        "Top 10 customers by total order value",
        "Monthly revenue for 2025",
        "Which product category has the highest average discount?",
        "How many orders were cancelled per region?",
    ]
    for example in examples:
        if st.button(example, use_container_width=True):
            st.session_state["question"] = example
    with st.expander("Tables the assistant can see"):
        st.code(schema_text, language="text")

question = st.text_input("Your question", key="question",
                         placeholder="e.g. Total sales by region in 2025")

if st.button("Ask", type="primary") and question:
    with st.spinner("Writing SQL and querying Oracle..."):
        result = answer_question(conn, question, schema_text)

    st.subheader("Generated SQL")
    st.code(result["sql"] or "", language="sql")

    if result.get("error"):
        st.error(f"Could not answer this question: {result['error']}")
    else:
        df: pd.DataFrame = result["data"]
        st.subheader("Answer")
        st.write(result["answer"])

        st.subheader("Data")
        st.dataframe(df, use_container_width=True)

        # Quick chart when the result is one label column + one number column
        if df.shape[1] == 2 and pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
            st.bar_chart(df.set_index(df.columns[0]))

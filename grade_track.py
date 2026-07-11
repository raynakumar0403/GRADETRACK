import os
import random
from datetime import datetime
import sqlite3

import pandas as pd
import plotly.express as px

import streamlit as st
from groq import Groq

# ============================================================
# SETTINGS
# ============================================================

DB_PATH = "data/gradetrack.db"

SUBJECTS = {
    "english": "English",
    "hindi": "Hindi",
    "mathematics": "Mathematics",
    "social_science": "Social Science",
    "science": "Science",
}

ASSESSMENTS = [
    "Unit 1",
    "Unit 2 Assessment",
    "Midterm Assessment",
    "Unit 3 Assessment",
    "Final Assessment",
]

ROLL_NUMBERS = list(range(1, 41))

GROQ_MODEL = "llama-3.3-70b-versatile"


# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def get_connection():
    """Open a connection to the SQLite database."""
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Create the tables the first time the app runs."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            roll_no INTEGER PRIMARY KEY,
            student_name TEXT
        )
    """)

    subject_columns = ", ".join(f"{s} REAL" for s in SUBJECTS)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS marks (
            roll_no INTEGER,
            assessment_name TEXT,
            {subject_columns},
            updated_at TEXT,
            UNIQUE(roll_no, assessment_name)
        )
    """)

    conn.commit()
    conn.close()


def save_marks(roll_no, assessment_name, marks_dict, student_name=""):
    """Save new marks, or update marks that already exist for this student and assessment."""
    conn = get_connection()
    cur = conn.cursor()

    # Save or update the student's name.
    cur.execute("SELECT * FROM students WHERE roll_no = ?", (roll_no,))
    existing_student = cur.fetchone()
    if existing_student is None:
        cur.execute("INSERT INTO students (roll_no, student_name) VALUES (?, ?)", (roll_no, student_name))
    elif student_name:
        cur.execute("UPDATE students SET student_name = ? WHERE roll_no = ?", (student_name, roll_no))

    # Check if marks already exist for this roll number and assessment.
    cur.execute("SELECT * FROM marks WHERE roll_no = ? AND assessment_name = ?", (roll_no, assessment_name))
    existing_marks = cur.fetchone()

    columns = list(SUBJECTS.keys())
    values = [marks_dict.get(c) for c in columns]
    now = str(datetime.now())

    if existing_marks:
        set_clause = ", ".join(f"{c} = ?" for c in columns)
        cur.execute(
            f"UPDATE marks SET {set_clause}, updated_at = ? WHERE roll_no = ? AND assessment_name = ?",
            (*values, now, roll_no, assessment_name),
        )
        action = "updated"
    else:
        col_list = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        cur.execute(
            f"INSERT INTO marks (roll_no, assessment_name, {col_list}, updated_at) VALUES (?, ?, {placeholders}, ?)",
            (roll_no, assessment_name, *values, now),
        )
        action = "created"

    conn.commit()
    conn.close()
    return action


def get_marks(roll_no, assessment_name):
    """Return saved marks for one student and assessment, or None if not entered yet."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM marks WHERE roll_no = ? AND assessment_name = ?", (roll_no, assessment_name))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {subject: row[subject] for subject in SUBJECTS}


def get_all_marks():
    """Return every saved mark as a pandas DataFrame."""
    conn = get_connection()
    subject_list = ", ".join(f"m.{s}" for s in SUBJECTS)
    df = pd.read_sql_query(
        f"""
        SELECT m.roll_no, COALESCE(s.student_name, '') AS student_name,
               m.assessment_name, {subject_list}, m.updated_at
        FROM marks m
        LEFT JOIN students s ON s.roll_no = m.roll_no
        """,
        conn,
    )
    conn.close()
    return df


def reset_all_data():
    """Delete every student and every saved mark."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM marks")
    cur.execute("DELETE FROM students")
    conn.commit()
    conn.close()


def load_demo_data():
    """Fill the database with random demo marks for all 40 students, so the
    dashboards can be explored right away."""
    reset_all_data()
    for roll_no in range(1, 41):
        base_ability = random.uniform(45, 95)
        trend = random.uniform(-4, 4)
        for i, assessment_name in enumerate(ASSESSMENTS):
            if random.random() < 0.08:
                continue  # skip some records so the app also shows missing data
            marks = {}
            for subject in SUBJECTS:
                value = base_ability + trend * i + random.uniform(-8, 8)
                value = max(0, min(100, value))
                marks[subject] = round(value, 1)
            save_marks(roll_no, assessment_name, marks)


# ============================================================
# CALCULATION FUNCTIONS (no AI here - plain Python only)
# ============================================================

def calculate_percentage(row):
    """Add up the subject marks a student has, and turn it into a percentage.
    Returns None if no subjects were entered for this row."""
    values = [row[s] for s in SUBJECTS if pd.notna(row[s])]
    if not values:
        return None
    total = sum(values)
    max_marks = 100 * len(values)
    return round((total / max_marks) * 100, 2)


def student_trend(df, roll_no):
    """Table of assessment name + percentage for one student, in order."""
    rows = df[df["roll_no"] == roll_no]
    result = []
    for _, row in rows.iterrows():
        result.append({"assessment_name": row["assessment_name"], "percentage": calculate_percentage(row)})
    return pd.DataFrame(result)


def overall_percentage(df, roll_no):
    """Overall percentage across every assessment the student has marks for.
    Returns (percentage, number_of_assessments_used)."""
    rows = df[df["roll_no"] == roll_no]
    if rows.empty:
        return None, 0

    total_marks = 0
    total_max = 0
    count = 0
    for _, row in rows.iterrows():
        values = [row[s] for s in SUBJECTS if pd.notna(row[s])]
        if not values:
            continue
        total_marks += sum(values)
        total_max += 100 * len(values)
        count += 1

    if total_max == 0:
        return None, 0
    return round((total_marks / total_max) * 100, 2), count


def rank_students(df, assessment_name):
    """Rank every student for one assessment, highest percentage first.
    Students with the same percentage share the same rank."""
    rows = df[df["assessment_name"] == assessment_name]
    table = []
    for _, row in rows.iterrows():
        pct = calculate_percentage(row)
        if pct is not None:
            table.append({"roll_no": row["roll_no"], "student_name": row["student_name"], "percentage": pct})

    result = pd.DataFrame(table)
    if result.empty:
        return result
    result = result.sort_values("percentage", ascending=False).reset_index(drop=True)
    result["rank"] = result["percentage"].rank(ascending=False, method="min").astype(int)
    return result


def class_average(df, assessment_name):
    """Average percentage of the whole class for one assessment."""
    ranked = rank_students(df, assessment_name)
    if ranked.empty:
        return None
    return round(ranked["percentage"].mean(), 2)


def subject_average(df, assessment_name, subject):
    """Average marks for one subject in one assessment."""
    rows = df[df["assessment_name"] == assessment_name]
    values = rows[subject].dropna()
    if values.empty:
        return None
    return round(values.mean(), 2)


def class_trend(df):
    """Class average percentage for each assessment, in order."""
    result = []
    for assessment_name in ASSESSMENTS:
        result.append({"assessment_name": assessment_name, "class_average": class_average(df, assessment_name)})
    return pd.DataFrame(result)


def detect_decline(df, roll_no):
    """Check if a student's percentage dropped by 5 or more points compared
    to the previous assessment. Returns None if no decline is found."""
    trend = student_trend(df, roll_no).dropna(subset=["percentage"])
    if len(trend) < 2:
        return None
    previous = trend.iloc[-2]["percentage"]
    latest = trend.iloc[-1]["percentage"]
    if latest <= previous - 5:
        return {
            "roll_no": roll_no,
            "previous_percentage": previous,
            "latest_percentage": latest,
            "drop": round(previous - latest, 2),
        }
    return None


def all_declining_students(df):
    """List of decline details for every student who is currently declining."""
    result = []
    for roll_no in df["roll_no"].unique():
        decline = detect_decline(df, roll_no)
        if decline:
            result.append(decline)
    return result


def overall_topper(df):
    """Find the student with the highest overall percentage. Returns (roll_no, percentage)."""
    best_roll_no = None
    best_percentage = -1
    for roll_no in df["roll_no"].unique():
        pct, _ = overall_percentage(df, roll_no)
        if pct is not None and pct > best_percentage:
            best_percentage = pct
            best_roll_no = roll_no
    return best_roll_no, best_percentage


def score_band_counts(df, assessment_name):
    """Count how many students fall into each score band for one assessment.
    Boundaries are written as (low, high] so decimal percentages like 60.5
    always land in exactly one band, with no gaps."""
    ranked = rank_students(df, assessment_name)
    bands = [("0-40", -1, 40), ("41-60", 40, 60), ("61-80", 60, 80), ("81-90", 80, 90), ("91-100", 90, 101)]
    result = []
    for label, low, high in bands:
        if ranked.empty:
            count = 0
        else:
            count = int(((ranked["percentage"] > low) & (ranked["percentage"] <= high)).sum())
        result.append({"band": label, "count": count})
    return pd.DataFrame(result)


# ============================================================
# GROQ AI FUNCTIONS
# Groq only explains numbers calculated above. It never does any
# calculation itself.
# ============================================================

def get_groq_client(api_key):
    """Create a Groq client using the given API key."""
    return Groq(api_key=api_key)


def check_api_key(api_key):
    """Try a tiny request to see if the API key actually works."""
    try:
        client = get_groq_client(api_key)
        client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5,
        )
        return True
    except Exception:
        return False


def ask_groq(client, prompt):
    """Send a prompt to Groq and return the text answer.
    Returns an error message (as text) if something goes wrong, instead of crashing the app."""
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant for a teacher. Only use the "
                                               "data given to you. Never invent facts about students that "
                                               "are not in the data."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error talking to Groq: {str(e)}"


def generate_student_summary(client, data):
    """Ask Groq for a short performance summary of one student."""
    prompt = f"""
Using only this data about one student, write a short performance summary:
overall performance, strengths, weaknesses, and one coaching suggestion.

DATA:
{data}
"""
    return ask_groq(client, prompt)


def generate_declining_students_summary(client, data):
    """Ask Groq to explain a list of students who are declining."""
    prompt = f"""
This is a list of students whose performance has dropped between two assessments.
For each student, write one sentence explaining the drop using the numbers given.

DATA:
{data}
"""
    return ask_groq(client, prompt)


def generate_class_summary(client, data):
    """Ask Groq to summarize the class's strengths and weaknesses."""
    prompt = f"""
Using only this class performance data, summarize the strongest subjects,
the weakest subjects, and one suggestion for the teacher to focus on.

DATA:
{data}
"""
    return ask_groq(client, prompt)


def generate_report_card_remarks(client, data, tone):
    """Ask Groq to write report card remarks for one student."""
    prompt = f"""
Write {tone} report card remarks for this student, based only on this data.
Keep it constructive and encouraging.

DATA:
{data}
"""
    return ask_groq(client, prompt)


def answer_question(client, data, question):
    """Ask Groq a free-form question, grounded only in the given data."""
    prompt = f"""
Answer this question using only the data below. If the data is not enough
to answer, say so plainly instead of guessing.

QUESTION: {question}

DATA:
{data}
"""
    return ask_groq(client, prompt)


# ============================================================
# STREAMLIT PAGES
# ============================================================

def page_access():
    st.title("📘 GradeTrack")
    st.write("Student Marks, Performance Analytics and AI Coaching Assistant")

    if "groq_api_key" not in st.session_state:
        st.subheader("Enter your Groq API key to enable AI features")
        st.write(
            "GradeTrack works as a marks and dashboard tool without a key. "
            "Add a Groq API key here to unlock AI summaries and the chatbot."
        )
        api_key = st.text_input("Groq API Key", type="password", placeholder="gsk_...")

        if st.button("Continue"):
            with st.spinner("Checking your key..."):
                works = check_api_key(api_key)
            if works:
                st.session_state["groq_api_key"] = api_key
                st.session_state["groq_client"] = get_groq_client(api_key)
                st.success("API key connected!")
                st.rerun()
            else:
                st.error("That key did not work. Please check it and try again.")

        st.caption("Your key is only kept for this session and is never saved to disk.")
        st.info("You can also open Data Management and load demo data to explore the app without a key.")
    else:
        st.success("Groq API key is connected.")
        st.write("Use the sidebar to move between pages: Marks Entry, Student Analysis, "
                 "Class Analysis, Rankings, AI Insights, and Data Management.")
        if st.button("Log Out / Clear API Key"):
            st.session_state.pop("groq_api_key", None)
            st.session_state.pop("groq_client", None)
            st.rerun()


def page_marks_entry(df):
    st.title("📝 Marks Entry")
    st.write("Pick an assessment and roll number, enter the five subject marks, then save.")

    col1, col2 = st.columns(2)
    assessment_name = col1.selectbox("Assessment", ASSESSMENTS)
    roll_no = col2.selectbox("Roll Number", ROLL_NUMBERS)

    existing = get_marks(roll_no, assessment_name)
    if existing:
        st.info("Loaded previously saved marks for this student and assessment.")

    existing_rows = df[df["roll_no"] == roll_no] if not df.empty else pd.DataFrame()
    existing_name = existing_rows["student_name"].iloc[0] if not existing_rows.empty else ""
    student_name = st.text_input("Student Name (optional)", value=existing_name)

    st.write("Subject marks (0-100, leave blank if not available):")
    cols = st.columns(5)
    entered = {}
    for (subject, label), col in zip(SUBJECTS.items(), cols):
        default = existing.get(subject) if existing else None
        entered[subject] = col.text_input(label, value="" if default is None else str(default))

    if st.button("💾 Save Marks", type="primary"):
        marks = {}
        error_found = False
        for subject, label in SUBJECTS.items():
            raw = entered[subject].strip()
            if raw == "":
                marks[subject] = None
                continue
            try:
                value = float(raw)
            except ValueError:
                st.error(f"{label}: '{raw}' is not a number.")
                error_found = True
                continue
            if value < 0 or value > 100:
                st.error(f"{label}: must be between 0 and 100.")
                error_found = True
                continue
            marks[subject] = value

        if not error_found:
            action = save_marks(roll_no, assessment_name, marks, student_name)
            st.success(f"Marks {action} for Roll Number {roll_no} — {assessment_name}.")
            st.rerun()


def page_student_analysis(df):
    st.title("📈 Student Analysis")
    roll_no = st.selectbox("Roll Number", ROLL_NUMBERS)

    rows = df[df["roll_no"] == roll_no]
    if rows.empty:
        st.info("No marks saved yet for this student. Go to Marks Entry to add records.")
        return

    student_name = rows["student_name"].iloc[0]
    if student_name:
        st.caption(f"Student: {student_name}")

    trend = student_trend(df, roll_no)
    overall_pct, count = overall_percentage(df, roll_no)

    valid_trend = trend.dropna(subset=["percentage"])
    latest_pct = valid_trend["percentage"].iloc[-1] if not valid_trend.empty else None

    col1, col2 = st.columns(2)
    col1.metric("Latest Percentage", f"{latest_pct}%" if latest_pct is not None else "No data")
    col2.metric("Overall Percentage", f"{overall_pct}%" if overall_pct is not None else "No data")
    st.caption(f"Overall percentage is based on {count} available assessment(s).")

    st.subheader("Trend Across Assessments")
    if not valid_trend.empty:
        fig = px.line(trend, x="assessment_name", y="percentage", markers=True)
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Marks Table")
    st.dataframe(rows[["assessment_name"] + list(SUBJECTS.keys())], hide_index=True, use_container_width=True)

    st.subheader("🤖 AI Performance Summary")
    if "groq_client" not in st.session_state:
        st.warning("Enter a Groq API key on the Access page first.")
    elif st.button("Generate Performance Summary"):
        data = {
            "roll_no": roll_no,
            "overall_percentage": overall_pct,
            "trend": valid_trend.to_dict(orient="records"),
            "decline": detect_decline(df, roll_no),
        }
        with st.spinner("Asking Groq..."):
            summary = generate_student_summary(st.session_state["groq_client"], data)
        st.write(summary)
        st.caption("AI-generated guidance — teacher review required.")


def page_class_analysis(df):
    st.title("📊 Class Analysis")
    if df.empty:
        st.info("No marks available yet. Go to Marks Entry first.")
        return

    assessment_name = st.selectbox("Assessment", ASSESSMENTS)

    avg = class_average(df, assessment_name)
    st.metric("Class Average", f"{avg}%" if avg is not None else "No data")

    st.subheader("Top 3 Students")
    ranked = rank_students(df, assessment_name)
    st.dataframe(ranked[ranked["rank"] <= 3], hide_index=True, use_container_width=True)

    st.subheader("Performance Distribution")
    bands = score_band_counts(df, assessment_name)
    fig = px.bar(bands, x="band", y="count")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Subject-wise Class Average")
    subject_table = pd.DataFrame(
        [{"subject": label, "average": subject_average(df, assessment_name, subject)}
         for subject, label in SUBJECTS.items()]
    )
    fig2 = px.bar(subject_table, x="subject", y="average")
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Class Average Trend")
    trend = class_trend(df)
    fig3 = px.line(trend, x="assessment_name", y="class_average", markers=True)
    st.plotly_chart(fig3, use_container_width=True)


def page_rankings(df):
    st.title("🏆 Rankings")
    if df.empty:
        st.info("No marks available yet. Go to Marks Entry first.")
        return

    topper_roll, topper_pct = overall_topper(df)
    if topper_roll is not None:
        col1, col2 = st.columns(2)
        col1.metric("Overall Topper (Roll No)", topper_roll)
        col2.metric("Overall Percentage", f"{topper_pct}%")

    assessment_name = st.selectbox("Assessment", ASSESSMENTS)
    ranked = rank_students(df, assessment_name)
    st.dataframe(ranked, hide_index=True, use_container_width=True)


def page_ai_insights(df):
    st.title("🤖 AI Insights")

    if "groq_client" not in st.session_state:
        st.warning("Enter a Groq API key on the Access page to use AI Insights.")
        return

    client = st.session_state["groq_client"]

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    st.subheader("Quick Actions")
    col1, col2, col3 = st.columns(3)

    if col1.button("📉 Show Declining Students"):
        declines = all_declining_students(df)
        if not declines:
            answer = "No student is currently declining."
        else:
            with st.spinner("Asking Groq..."):
                answer = generate_declining_students_summary(client, declines)
        st.session_state["chat_history"].append(answer)

    if col2.button("📚 Class Strengths & Weaknesses"):
        data = {
            "class_trend": class_trend(df).to_dict(orient="records"),
        }
        with st.spinner("Asking Groq..."):
            answer = generate_class_summary(client, data)
        st.session_state["chat_history"].append(answer)

    if col3.button("✍️ Report Card Remarks"):
        roll_no = st.session_state.get("remarks_roll_no", ROLL_NUMBERS[0])
        overall_pct, count = overall_percentage(df, roll_no)
        data = {"roll_no": roll_no, "overall_percentage": overall_pct}
        with st.spinner("Asking Groq..."):
            answer = generate_report_card_remarks(client, data, "concise")
        st.session_state["chat_history"].append(answer)

    st.session_state["remarks_roll_no"] = st.selectbox(
        "Roll number used for Report Card Remarks", ROLL_NUMBERS, key="remarks_roll_no_select"
    )

    st.subheader("Ask GradeTrack a Question")
    question = st.text_input("Your question", placeholder="Which students improved the most?")
    if st.button("Ask") and question:
        data = {
            "class_trend": class_trend(df).to_dict(orient="records"),
            "declining_students": all_declining_students(df),
        }
        with st.spinner("Asking Groq..."):
            answer = answer_question(client, data, question)
        st.session_state["chat_history"].append(answer)

    st.subheader("Conversation")
    for message in reversed(st.session_state["chat_history"]):
        st.write(message)
        st.caption("AI-generated guidance — teacher review required.")
        st.divider()


def page_data_management(df):
    st.title("🗂️ Data Management")

    st.subheader("Export")
    if not df.empty:
        st.download_button("⬇️ Download All Marks (CSV)", df.to_csv(index=False), file_name="gradetrack_marks.csv")
    else:
        st.caption("No data to export yet.")

    st.subheader("Demo Data")
    if st.button("📥 Load Demo Data"):
        load_demo_data()
        st.success("Demo data loaded for 40 students.")
        st.rerun()

    confirm = st.checkbox("I understand this deletes all current marks.")
    if st.button("🗑️ Reset All Data", disabled=not confirm):
        reset_all_data()
        st.success("All data cleared.")
        st.rerun()


# ============================================================
# MAIN APP
# ============================================================

def main():
    st.set_page_config(page_title="GradeTrack", page_icon="📘", layout="wide")
    init_database()

    df = get_all_marks()

    st.sidebar.title("📘 GradeTrack")
    page = st.sidebar.radio(
        "Go to",
        ["Access", "Marks Entry", "Student Analysis", "Class Analysis", "Rankings", "AI Insights", "Data Management"],
    )

    if page == "Access":
        page_access()
    elif page == "Marks Entry":
        page_marks_entry(df)
    elif page == "Student Analysis":
        page_student_analysis(df)
    elif page == "Class Analysis":
        page_class_analysis(df)
    elif page == "Rankings":
        page_rankings(df)
    elif page == "AI Insights":
        page_ai_insights(df)
    elif page == "Data Management":
        page_data_management(df)


if __name__ == "__main__":
    main()
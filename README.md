# GradeTrack

**Student Marks, Performance Analytics and AI Coaching Assistant**

GradeTrack is a Streamlit application that helps a teacher record marks
for one class of 40 students, view deterministic performance dashboards,
identify students who may need coaching, and request AI-generated
coaching insights through the Groq API.

> **Design rule:** Groq never calculates marks, percentages, ranks, or
> averages. All calculations are performed in Python using fixed,
> testable formulas. Groq only explains results that Python already
> calculated.

---

## 1. Architecture Overview

```
gradetrack/
├── app.py                     # Entry point: Access screen (Groq API key gate)
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
├── pages/                     # One file per Streamlit page (auto-listed in sidebar)
│   ├── 1_Marks_Entry.py
│   ├── 2_Student_Analysis.py
│   ├── 3_Class_Analysis.py
│   ├── 4_Rankings.py
│   ├── 5_AI_Insights.py
│   └── 6_Data_Management.py
├── services/                  # No Streamlit imports — pure logic, unit-testable
│   ├── constants.py           # Subjects, assessments, score bands, decline rule
│   ├── database.py            # SQLite access (create, read, upsert marks)
│   ├── analytics.py           # ALL calculations: percentages, ranks, trends, decline
│   ├── groq_service.py        # Groq API calls + task-specific prompts
│   └── export_service.py      # CSV / Excel export helpers
├── components/                # Streamlit UI helpers shared across pages
│   ├── auth.py                # API key gate, session state, logout
│   ├── charts.py               # Plotly chart builders
│   └── styles.py               # Shared CSS, sidebar block, metric cards
├── data/
│   └── gradetrack.db          # Created automatically on first run (not tracked in git)
└── tests/
    ├── test_analytics.py      # Calculation correctness (percentages, ranks, decline)
    ├── test_database.py       # Insert/update/unique-constraint/reload behaviour
    └── test_validation.py     # Marks input validation rules
```

### How data flows (the "student demo" explanation)

1. Teacher enters marks for a student/assessment on **Marks Entry** →
   saved to SQLite (`services/database.py`).
2. Every dashboard page reads marks with
   `database.get_all_marks_df()` and passes that DataFrame into
   `services/analytics.py`, which computes percentages, class
   averages, rankings, trends, and decline flags — all in plain
   Python, all testable, all with no AI involved.
3. Charts (`components/charts.py`) draw the already-calculated
   numbers using Plotly.
4. On **AI Insights**, the teacher can ask Groq to *explain* those
   same calculated numbers in plain language. Groq receives only a
   structured JSON-like summary built from `analytics.py` output —
   never raw database access, and never asked to compute a number
   itself.

This separation means the static dashboards keep working perfectly
even if the Groq API key is missing, invalid, or the service is down.

---

## 2. Local Setup

### Prerequisites
- Python 3.11 or newer
- A free [Groq API key](https://console.groq.com/keys) (optional —
  only needed for the AI Insights page)

### Steps

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd gradetrack

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
streamlit run app.py
```

The app opens at `http://localhost:8501`. The SQLite database is
created automatically at `data/gradetrack.db` on first run.

Enter your Groq API key on the Access screen to enable AI Insights,
or skip it — Marks Entry, Class Analysis, and Rankings all work
without a key. You can also load **Demo Data** from the
**Data Management** page to explore the dashboards immediately.

### Optional: local `.env` for development

Copy `.env.example` to `.env` and fill in a key for your own local
convenience (e.g. to prefill a variable in a helper script). The
deployed app itself always collects the key through the Access
screen UI — the `.env` value is never read automatically by `app.py`.

---

## 3. Deploying to Streamlit Community Cloud

1. Push this repository to GitHub (see section 4 below).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in
   with GitHub.
3. Click **New app**, select this repository, branch `main`, and set
   the main file path to `app.py`.
4. Deploy. Streamlit Cloud will install everything from
   `requirements.txt` automatically.
5. Each teacher who opens the deployed app enters their own Groq API
   key in the Access screen — the key is kept only in that browser
   session's `st.session_state` and is never stored by the app.

**Note on storage:** Streamlit Community Cloud's filesystem is
ephemeral on redeploys/restarts — `data/gradetrack.db` may reset when
the app is redeployed or goes to sleep. This is fine for a
demonstration or classroom prototype. For durable long-term storage,
replace the SQLite file with a hosted database (e.g. Postgres) behind
the same `services/database.py` interface — no other file needs to
change, since all data access goes through that module.

---

## 4. Publishing to GitHub

```bash
git init
git add .
git commit -m "Initial commit: GradeTrack v1"
git branch -M main
git remote add origin https://github.com/<your-username>/gradetrack.git
git push -u origin main
```

`.gitignore` already excludes `.env`, the SQLite database file, and
Python cache directories, so no secrets or generated data are pushed.

---

## 5. Running Tests

```bash
pip install pytest
pytest tests/ -v
```

Tests cover:
- **Validation** — blank, negative, above-100, decimal, and valid marks.
- **Analytics** — percentages (complete and partial data), overall
  percentage across varying numbers of assessments, standard
  competition ranking with ties, decline detection (single big drop,
  two consecutive small declines, and no-decline cases), and score
  band distribution.
- **Database** — insert, update-without-duplicate (unique constraint
  on roll number + assessment), and reload-after-restart behaviour.

---

## 6. Key Business Rules (for quick reference)

| Rule | Detail |
|---|---|
| Roll numbers | 1–40, one class only in Version 1 |
| Subjects | English, Hindi, Mathematics, Social Science, Science — each out of 100 |
| Assessments | Unit 1, Unit 2 Assessment, Midterm Assessment, Unit 3 Assessment, Final Assessment |
| Assessment percentage | Total of available subject marks ÷ (100 × number of available subjects) × 100 |
| Overall percentage | Sum of all available marks ÷ sum of maximum marks for all available records × 100 |
| Ranking | Standard competition ranking (1, 2, 2, 4); ties ordered by roll number for display |
| Decline rule | Latest percentage ≥5 points below the previous assessment, OR two consecutive declines |
| AI key storage | Session-only (`st.session_state`); never written to disk, database, or logs |

---

## 7. Out of Scope (Version 1)

Multiple schools/branches, attendance/fees/timetable/homework,
parent or student login, ERP integration, automated messaging to
parents, and enterprise-scale identity management are explicitly out
of scope for this version (see the requirements docum

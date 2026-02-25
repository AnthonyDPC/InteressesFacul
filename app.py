from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
import sqlite3
from datetime import datetime
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# ========================= DATABASE SETUP =========================
def init_db():
    with sqlite3.connect('careerfit.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     email TEXT UNIQUE NOT NULL,
                     password TEXT NOT NULL,
                     created_at TEXT)''')
        c.executemany('''CREATE TABLE IF NOT EXISTS results (
                         id INTEGER PRIMARY KEY AUTOINCREMENT,
                         user_id INTEGER,
                         bigfive TEXT,
                         interests TEXT,
                         cognitive TEXT,
                         completed_at TEXT,
                         FOREIGN KEY(user_id) REFERENCES users(id))''', ())
        conn.commit()

init_db()

# ========================= USER MODEL =========================
class User(UserMixin):
    def __init__(self, id, email):
        self.id = id
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect('careerfit.db') as conn:
        c = conn.cursor()
        c.execute("SELECT id, email FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        if row:
            return User(row[0], row[1])
    return None

# ========================= SAVE RESULTS TO DB =========================
def save_results_to_db():
    if not current_user.is_authenticated:
        return
    
    with sqlite3.connect('careerfit.db') as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO results 
                     (user_id, bigfive, interests, cognitive, completed_at)
                     VALUES (?, ?, ?, ?, ?)""",
                  (current_user.id,
                   str(session.get("bigfive")),
                   str(session.get("interests")),
                   str(session.get("cognitive")),
                   datetime.now().isoformat()))
        conn.commit()

# ========================= ROUTES =========================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        
        if len(password) < 6:
            flash("Password must be at least 6 characters", "danger")
            return render_template("register.html")
        
        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        
        try:
            with sqlite3.connect('careerfit.db') as conn:
                c = conn.cursor()
                c.execute("INSERT INTO users (email, password, created_at) VALUES (?, ?, ?)",
                          (email, hashed, datetime.now().isoformat()))
                conn.commit()
            flash("Account created! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.", "danger")
    
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        
        with sqlite3.connect('careerfit.db') as conn:
            c = conn.cursor()
            c.execute("SELECT id, email, password FROM users WHERE email = ?", (email,))
            user = c.fetchone()
        
        if user and bcrypt.check_password_hash(user[2], password):
            login_user(User(user[0], user[1]))
            flash("Logged in successfully!", "success")
            return redirect(url_for("home"))
        else:
            flash("Invalid email or password", "danger")
    
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("home"))

# ========================= PROTECTED ROUTES =========================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/final_results")
@login_required  # optional but good
def final_results():
    completed = session.get("completed_tests", [])
    if len(completed) < 3:
        flash("Please complete all three tests first.", "warning")
        return redirect(url_for("home"))
    
    # Save results once (prevent duplicates on refresh)
    if not session.get("results_saved"):
        save_results_to_db()
        session["results_saved"] = True
    
    bf = session["bigfive"]["perc"]
    int_res = session["interests"]
    cog = session["cognitive"]
    
    top_jobs, bad_fits = get_major_recommendations(bf, int_res["top2"], cog["estimated_sat"])
    
    # For summary cards (update final_results.html if needed)
    summary_personality = " • ".join([f"High {t}" for t, v in bf.items() if v > 70]) or "Balanced"
    
    return render_template("final_results.html", 
                           top_jobs=top_jobs, 
                           bad_fits=bad_fits,
                           top2=int_res["top2"], 
                           estimated_iq=cog["estimated_sat"],  # now SAT score
                           band="Estimated SAT",
                           summary_personality=summary_personality)


# ========================= START OF THE CODE =========================

# BIG 5 PERSONALITY TRAITS (exact public-domain wording) + reverse scoring info
QUESTIONS = [
    # Extraversion (1-10)
    ("I am the life of the party.", False),
    ("I feel comfortable around people.", False),
    ("I start conversations.", False),
    ("I talk to a lot of different people at parties.", False),
    ("I don't mind being the center of attention.", False),
    ("I am quiet around strangers.", True),
    ("I don't talk a lot.", True),
    ("I keep in the background.", True),
    ("I have little to say.", True),
    ("I don't like to draw attention to myself.", True),

    # Agreeableness (11-20)
    ("I feel little concern for others.", True),
    ("I am interested in people.", False),
    ("I insult people.", True),
    ("I sympathize with others' feelings.", False),
    ("I am not interested in other people's problems.", True),
    ("I have a soft heart.", False),
    ("I am not really interested in others.", True),
    ("I take time out for others.", False),
    ("I feel others' emotions.", False),
    ("I make people feel at ease.", False),

    # Conscientiousness (21-30)
    ("I am always prepared.", False),
    ("I leave my belongings around.", True),
    ("I pay attention to details.", False),
    ("I make a mess of things.", True),
    ("I get chores done right away.", False),
    ("I often forget to put things back in their proper place.", True),
    ("I like order.", False),
    ("I shirk my duties.", True),
    ("I follow a schedule.", False),
    ("I am exacting in my work.", False),

    # Neuroticism (31-40)
    ("I get stressed out easily.", False),
    ("I am relaxed most of the time.", True),
    ("I worry about things.", False),
    ("I seldom feel blue.", True),
    ("I am easily disturbed.", False),
    ("I get upset easily.", False),
    ("I change my mood a lot.", False),
    ("I have frequent mood swings.", False),
    ("I get irritated easily.", False),
    ("I often feel blue.", False),

    # Openness (41-50)
    ("I have a rich vocabulary.", False),
    ("I have difficulty understanding abstract ideas.", True),
    ("I have a vivid imagination.", False),
    ("I am not interested in abstract ideas.", True),
    ("I have excellent ideas.", False),
    ("I do not have a good imagination.", True),
    ("I am quick to understand things.", False),
    ("I use difficult words.", False),
    ("I spend time reflecting on things.", False),
    ("I am full of ideas.", False),
]
# Improved NORM_TABLE: Raw score cutoffs for ~10th-90th percentiles (based on IPIP adult norms)
# Each trait raw: 10-50 possible. These are approximate medians for percentile mapping.
NORM_TABLE = {
    "E": [15, 20, 25, 30, 35, 40, 42, 45, 48, 50],   # Extraversion
    "A": [18, 22, 26, 30, 34, 38, 40, 42, 45, 48],   # Agreeableness
    "C": [20, 25, 30, 35, 38, 40, 42, 45, 48, 50],   # Conscientiousness
    "N": [25, 30, 35, 38, 40, 42, 45, 48, 50, 50],   # Neuroticism (higher raw = higher percentile for neuroticism)
    "O": [22, 27, 32, 36, 40, 42, 45, 48, 49, 50],   # Openness
}


# INTERESTS
INTEREST_QUESTIONS = [
    # Realistic (5)
    "Repair cars or trucks",
    "Work with tools and machinery",
    "Do woodworking",
    "Construct new buildings",
    "Operate heavy equipment",

    # Investigative (5)
    "Design a laboratory experiment",
    "Solve complex puzzles",
    "Develop a computer program",
    "Carry out medical research",
    "Explain scientific concepts to others",

    # Artistic (5)
    "Create works of art",
    "Write short stories or novels",
    "Design Internet web pages",
    "Act in a play",
    "Play an instrument in an orchestra",

    # Social (5)
    "Help others learn new ideas",
    "Counsel persons who need help",
    "Care for sick people",
    "Teach children",
    "Provide comfort and support to others",

    # Enterprising (5)
    "Lead other people",
    "Persuade others to buy something",
    "Plan an advertising campaign",
    "Make important decisions affecting many people",
    "Organize a political campaign",

    # Conventional (5)
    "Keep detailed records",
    "Manage a computer database",
    "Plan budgets",
    "Develop an office filing system",
    "Monitor business expenses",
]

RIASEC_MAPPING = {
    "R": INTEREST_QUESTIONS[0:5],    # Realistic
    "I": INTEREST_QUESTIONS[5:10],   # Investigative
    "A": INTEREST_QUESTIONS[10:15],  # Artistic
    "S": INTEREST_QUESTIONS[15:20],  # Social
    "E": INTEREST_QUESTIONS[20:25],  # Enterprising
    "C": INTEREST_QUESTIONS[25:30],  # Conventional
}


# ======================== UPDATED: COGNITIVE (SAT-STYLE VOCAB) ========================
# 15 medium-hard SAT-level vocab questions (real-style multiple choice)

SAT_VOCAB_QUESTIONS = [
    {"question": "The politician's _________ promises during the campaign turned out to be empty rhetoric once in office.",
     "options": ["effusive", "vacuous", "cogent", "pragmatic"], "correct": 1},
    {"question": "Her _________ demeanor in the face of criticism impressed the interviewers.",
     "options": ["belligerent", "equable", "petulant", "obstreperous"], "correct": 1},
    {"question": "The professor's lecture was so _________ that many students struggled to follow the complex argument.",
     "options": ["lucid", "esoteric", "pedestrian", "candid"], "correct": 1},
    {"question": "Despite the team's loss, the coach refused to _________ blame on any individual player.",
     "options": ["mitigate", "ascribe", "exacerbate", "obviate"], "correct": 1},
    {"question": "The novel's _________ ending left readers debating the characters' true motivations.",
     "options": ["unequivocal", "ambiguous", "didactic", "trite"], "correct": 1},
    {"question": "His _________ spending habits eventually led to financial ruin.",
     "options": ["parsimonious", "profligate", "frugal", "judicious"], "correct": 1},
    {"question": "The scientist's theory was initially met with _________ from the academic community.",
     "options": ["acclaim", "derision", "deference", "approbation"], "correct": 1},
    {"question": "The artist's work is known for its _________ use of color and form.",
     "options": ["austere", "florid", "spartan", "minimalist"], "correct": 1},
    {"question": "She delivered a _________ critique of the policy, pointing out every flaw.",
     "options": ["temperate", "scathing", "laudatory", "anodyne"], "correct": 1},
    {"question": "The ancient text was _________ with obscure references that required extensive footnotes.",
     "options": ["replete", "devoid", "bereft", "lacking"], "correct": 0},
    {"question": "His _________ attitude made him unpopular among colleagues who valued collaboration.",
     "options": ["gregarious", "solitary", "altruistic", "magnanimous"], "correct": 1},
    {"question": "The committee's decision was _________ by political considerations rather than merit.",
     "options": ["informed", "vitiated", "bolstered", "buttressed"], "correct": 1},
    {"question": "The speaker's _________ delivery captivated the audience for hours.",
     "options": ["monotonous", "eloquent", "inarticulate", "halting"], "correct": 1},
    {"question": "Environmentalists argue that current policies _________ the effects of climate change.",
     "options": ["ameliorate", "exacerbate", "palliate", "alleviate"], "correct": 1},
    {"question": "The biography avoids _________ in favor of a balanced portrayal.",
     "options": ["hagiography", "objectivity", "candor", "veracity"], "correct": 0},
]

COGNITIVE_QUESTIONS = SAT_VOCAB_QUESTIONS  # Use the SAT-style list


# ======================== NEW: COLLEGE MAJORS DATABASE ========================
# Each major has:
# - name
# - primary_riasec: top 2 Holland codes (string like "IA")
# - bigfive_profile: approximate percentile means (from meta-analyses like Vedel 2014 & others)
# - avg_sat: average SAT for students intending/graduating in this major (from NCES Table 226.40, College Board data ~2023-2024)
# - why_personality: short explanation for Big Five fit
# - persistence_bonus: rough % higher persistence for good RIASEC fit (based on meta ~0.34 correlation)

MAJORS_DATABASE = [
    {"name": "Physics", "primary_riasec": "IR", "bigfive_profile": {"O": 85, "C": 75, "A": 45, "E": 40, "N": 50},
     "avg_sat": 1350, "why_personality": "High Openness for abstract thinking, moderate Conscientiousness for rigorous work"},
     
    {"name": "Computer Science", "primary_riasec": "IC", "bigfive_profile": {"O": 80, "C": 70, "A": 40, "E": 50, "N": 45},
     "avg_sat": 1320, "why_personality": "High Openness & Conscientiousness for problem-solving and detail"},
     
    {"name": "Engineering (General)", "primary_riasec": "RI", "bigfive_profile": {"O": 75, "C": 80, "A": 45, "E": 55, "N": 40},
     "avg_sat": 1300, "why_personality": "Strong Conscientiousness for precision, moderate Openness"},
     
    {"name": "Mathematics", "primary_riasec": "IC", "bigfive_profile": {"O": 82, "C": 78, "A": 42, "E": 38, "N": 48},
     "avg_sat": 1340, "why_personality": "Very high Openness and Conscientiousness for theoretical rigor"},
     
    {"name": "Biology", "primary_riasec": "IR", "bigfive_profile": {"O": 78, "C": 72, "A": 55, "E": 45, "N": 52},
     "avg_sat": 1250, "why_personality": "High Openness for scientific curiosity"},
     
    {"name": "Psychology", "primary_riasec": "SI", "bigfive_profile": {"O": 80, "C": 60, "A": 70, "E": 50, "N": 55},
     "avg_sat": 1180, "why_personality": "High Openness & Agreeableness for understanding people"},
     
    {"name": "English / Literature", "primary_riasec": "AS", "bigfive_profile": {"O": 90, "C": 55, "A": 65, "E": 45, "N": 60},
     "avg_sat": 1220, "why_personality": "Very high Openness for creativity and introspection"},
     
    {"name": "Art / Fine Arts", "primary_riasec": "A", "bigfive_profile": {"O": 95, "C": 50, "A": 60, "E": 40, "N": 65},
     "avg_sat": 1150, "why_personality": "Extremely high Openness for artistic expression"},
     
    {"name": "Nursing", "primary_riasec": "SI", "bigfive_profile": {"O": 65, "C": 85, "A": 85, "E": 60, "N": 45},
     "avg_sat": 1180, "why_personality": "High Agreeableness & Conscientiousness for caring roles"},
     
    {"name": "Business Administration", "primary_riasec": "EC", "bigfive_profile": {"O": 60, "C": 75, "A": 55, "E": 80, "N": 40},
     "avg_sat": 1200, "why_personality": "High Extraversion & Conscientiousness for leadership"},
     
    {"name": "Education", "primary_riasec": "S", "bigfive_profile": {"O": 65, "C": 70, "A": 85, "E": 65, "N": 50},
     "avg_sat": 1120, "why_personality": "High Agreeableness for helping and teaching"},
     
    {"name": "Sociology", "primary_riasec": "SA", "bigfive_profile": {"O": 82, "C": 60, "A": 75, "E": 50, "N": 58},
     "avg_sat": 1160, "why_personality": "High Openness & Agreeableness for social insight"},
     
    # Add more as needed – 12 is enough for MVP
]

def calculate_bigfive(answers):
    if len(answers) != 50:
        raise ValueError(f"Expected 50 answers, got {len(answers)}. Please answer all questions.")

    scores = {"E": 0, "A": 0, "C": 0, "N": 0, "O": 0}
    for i, (q, reverse) in enumerate(QUESTIONS):
        try:
            val = int(answers[i])
            if val < 1 or val > 5:
                raise ValueError(f"Invalid answer for question {i+1}: {val}")
            if reverse:
                val = 6 - val
            trait = "EACNO"[i // 10]
            scores[trait] += val
        except (ValueError, IndexError) as e:
            raise ValueError(f"Error processing question {i+1}: {e}")

    # Convert raw to percentile (linear interpolation for smoothness)
    percentiles = {}
    for trait, raw in scores.items():
        norms = NORM_TABLE[trait]
        if raw <= norms[0]:
            percentiles[trait] = 5  # Below 10th
        elif raw >= norms[-1]:
            percentiles[trait] = 95  # Above 90th
        else:
            # Find bracket and interpolate
            for p in range(len(norms) - 1):
                if norms[p] <= raw < norms[p + 1]:
                    low_p, high_p = p * 10, (p + 1) * 10
                    low_raw, high_raw = norms[p], norms[p + 1]
                    percentiles[trait] = low_p + ((raw - low_raw) / (high_raw - low_raw)) * (high_p - low_p)
                    break

    return scores, percentiles

def calculate_interests(answers):
    if len(answers) != 30:
        raise ValueError("Must answer all 30 questions")
    
    scores = {"R": 0, "I": 0, "A": 0, "S": 0, "E": 0, "C": 0}
    for i, val in enumerate(answers):
        val = int(val)
        for code, items in RIASEC_MAPPING.items():
            if INTEREST_QUESTIONS[i] in items:
                scores[code] += val
                break
    
    # Normalize to 0-100 for easy comparison
    normalized = {k: (v / (len(RIASEC_MAPPING[k]) * 5)) * 100 for k, v in scores.items()}
    
    # Top 2 codes
    sorted_codes = sorted(normalized, key=normalized.get, reverse=True)
    top2 = "".join(sorted_codes[:2])
    
    return scores, normalized, top2

# Scoring: 0–15 correct → estimated SAT score (400-1600 scale)
def calculate_cognitive(answers):
    if len(answers) != 15:
        raise ValueError("All 15 questions required")
    
    correct = sum(1 for i, ans in enumerate(answers) if ans and int(ans) == COGNITIVE_QUESTIONS[i]["correct"])
    
    # Approximate conversion: 0 correct ≈ 400, 15 correct ≈ 1500+ (real SAT vocab is part of broader test)
    estimated_sat = 400 + (correct / 15) * 1100
    estimated_sat = int(round(estimated_sat, -1))  # round to nearest 10
    
    return {
        "correct": correct,
        "total": 15,
        "estimated_sat": estimated_sat,
        "label": "Estimated Digital SAT Score"
    }

# ======================== NEW: RECOMMENDATION LOGIC ========================
def get_major_recommendations(bigfive_perc, interests_top2, estimated_sat):
    # Step 1: Personality fit score (Euclidean distance to major's Big Five profile)
    def personality_fit(user_perc, major_profile):
        distances = []
        for trait in ["O", "C", "A", "E", "N"]:
            user = user_perc.get(trait, 50)
            major = major_profile.get(trait, 50)
            distances.append((user - major) ** 2)
        return 100 - (sum(distances) ** 0.5) * 2  # normalize to ~0-100%
    
    # Step 2: RIASEC congruence (simple match on top2)
    def riasec_congruence(user_top2, major_code):
        match_count = len(set(user_top2) & set(major_code))
        return match_count * 50  # 0, 50, or 100
    
    # Step 3: SAT advantage (user SAT - avg major SAT)
    def sat_advantage(user_sat, avg_sat):
        diff = user_sat - avg_sat
        if diff > 100:
            return 30
        elif diff > 0:
            return 20
        elif diff > -100:
            return 0
        else:
            return -20  # slight penalty for big stretch
    
    recommendations = []
    bad_fits = []
    
    for major in MAJORS_DATABASE:
        p_fit = personality_fit(bigfive_perc, major["bigfive_profile"])
        r_fit = riasec_congruence(interests_top2, major["primary_riasec"])
        s_adv = sat_advantage(estimated_sat, major["avg_sat"])
        
        total_fit = (p_fit * 0.4) + (r_fit * 0.4) + (s_adv * 0.2)  # weighted
        
        entry = {
            "name": major["name"],
            "fit": round(total_fit),
            "why": f"{major['why_personality']}. High interest fit boosts persistence ~30%. Your estimated SAT gives you {'an edge' if s_adv > 0 else 'a realistic challenge'}.",
            "salary": "Varies $60k–$150k+",  # placeholder
            "growth": "Strong demand",
            "satisfaction": "High for good fit"
        }
        
        recommendations.append((total_fit, entry))
    
    # Sort and split
    recommendations.sort(reverse=True)
    top_jobs = [entry for _, entry in recommendations[:8]]
    bad_fits = [entry["name"] for _, entry in recommendations[-5:]]
    
    return top_jobs, bad_fits

# BIG FIVE --------------------------------------------------------------
@app.route("/bigfive", methods=["GET", "POST"])
def bigfive():
    if request.method == "POST":
        answers = [request.form.get(f"q{i}") for i in range(50)]
        try:
            raw, perc = calculate_bigfive(answers)
            session["bigfive"] = {"raw": raw, "perc": perc}

            # THIS WAS MISSING — ADD BIGFIVE TO COMPLETED LIST!
            completed = session.get("completed_tests", [])
            if "bigfive" not in completed:
                completed.append("bigfive")
                session["completed_tests"] = completed
                session.pop("results_saved", None)  # allow re-saving if retaken

            return redirect(url_for("results_bigfive"))
        except ValueError as e:
            return render_template("bigfive.html", questions=enumerate(QUESTIONS), error=str(e))

    return render_template("bigfive.html", questions=enumerate(QUESTIONS), error=None)

@app.route("/results/bigfive")
def results_bigfive():
    results = session.get("bigfive")
    if not results:
        return redirect(url_for("bigfive"))
    return render_template("results_bigfive.html", raw=results["raw"], perc=results["perc"])

# INTERESTS --------------------------------------------------------------
@app.route("/interests", methods=["GET", "POST"])
def interests():
    if request.method == "POST":
        answers = [request.form.get(f"q{i}") for i in range(30)]
        try:
            raw, norm, top2 = calculate_interests(answers)
            session["interests"] = {"raw": raw, "norm": norm, "top2": top2}
            # Unlock logic
            completed = session.get("completed_tests", [])
            if "interests" not in completed:
                completed.append("interests")
                session["completed_tests"] = completed
                session.pop("results_saved", None)  # Allow re-saving if they retake
            return redirect(url_for("results_interests"))
        except ValueError as e:
            return render_template("interests.html", questions=INTEREST_QUESTIONS, error=str(e))
    
    return render_template("interests.html", questions=INTEREST_QUESTIONS, error=None)

@app.route("/results/interests")
def results_interests():
    results = session.get("interests")
    if not results:
        return redirect(url_for("interests"))
    return render_template("results_interests.html", norm=results["norm"], top2=results["top2"])

# COGNITIVE --------------------------------------------------------------
@app.route("/cognitive", methods=["GET", "POST"])
def cognitive():
    if request.method == "POST":
        answers = [request.form.get(f"q{i}") for i in range(15)]
        try:
            results = calculate_cognitive(answers)
            session["cognitive"] = results
            
            # Track completion
            completed = session.get("completed_tests", [])
            if "cognitive" not in completed:
                completed.append("cognitive")
            if "bigfive" not in completed and session.get("bigfive"):
                completed.append("bigfive")   # this line was missing or broken
            session["completed_tests"] = completed
        
            return redirect(url_for("results_cognitive"))
        except ValueError as e:
            return render_template("cognitive.html", questions=enumerate(COGNITIVE_QUESTIONS), error=str(e))
    
    return render_template("cognitive.html", questions=enumerate(COGNITIVE_QUESTIONS))

@app.route("/results/cognitive")
def results_cognitive():
    results = session.get("cognitive")
    if not results:
        return redirect(url_for("cognitive"))
    return render_template("results_cognitive.html", **results)
  
# ——————————————————————— DEBUG: INSTANT UNLOCK (REMOVE BEFORE LAUNCH) ———————————————————————
@app.route("/debug_unlock")
def debug_unlock():
    """TEMPORARY ROUTE — instantly completes all tests for fast testing"""
    session["completed_tests"] = ["bigfive", "interests", "cognitive"]
    
    # Fake some realistic results so final_results doesn't crash
    session["bigfive"] = {"perc": {"E": 65, "A": 55, "C": 70, "N": 30, "O": 85}}
    session["interests"] = {"top2": "IA", "norm": {"I": 95, "A": 80, "R": 30, "S": 60, "E": 45, "C": 40}}
    session["cognitive"] = {"estimated_sat": 1300, "label": "Estimated Digital SAT Score"}
    
    session["results_saved"] = True  # prevent double-saving
    
    flash("DEBUG MODE: All tests instantly completed!", "success")
    return redirect(url_for("home"))
# —————————————————————————————————————————————————————————————————————————————————————————— 
   
if __name__ == "__main__":
    app.run(debug=True)
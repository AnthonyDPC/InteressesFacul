from flask import Flask, render_template, request, session, redirect, url_for, flash
import secrets
import json
import os

app = Flask(__name__)
app.secret_key = secrets.token_hex(24)
# ====================== CARREGAR DADOS (JSON) ======================
# Usamos app.root_path para garantir que o Flask encontre o arquivo 
# independentemente de onde o script seja executado no terminal.
json_path = os.path.join(app.root_path, 'data.json')

with open(json_path, 'r', encoding='utf-8') as f:
    db = json.load(f)

QUESTIONS = db["QUESTIONS"]
NORM_TABLE = db["NORM_TABLE"]
INTEREST_QUESTIONS = db["INTEREST_QUESTIONS"]
RIASEC_MAPPING = db["RIASEC_MAPPING"]
MAJORS_DATABASE = db["MAJORS_DATABASE"]

# ====================== FUNÇÕES DE CÁLCULO ======================
def calculate_bigfive(answers):
    scores = {"E": 0, "A": 0, "C": 0, "N": 0, "O": 0}
    for i, (q, reverse) in enumerate(QUESTIONS):
        val = int(answers[i])
        if reverse: val = 6 - val
        trait = "EACNO"[i // 10]
        scores[trait] += val
        
    # Cálculo simples de "percentil" baseado no max score de 50 por traço para a lógica funcionar
    perc = {trait: (score / 50) * 100 for trait, score in scores.items()}
    return scores, perc

def calculate_interests(answers):
    scores = {"R":0,"I":0,"A":0,"S":0,"E":0,"C":0}
    for i, val in enumerate(answers):
        val = int(val)
        for code, items in RIASEC_MAPPING.items():
            if INTEREST_QUESTIONS[i] in items:
                scores[code] += val
    top2 = "".join(sorted(scores, key=scores.get, reverse=True)[:2])
    return scores, top2

def recomendar_cursos(bigfive_perc, top_interesses, nota_enem):
    recomendados = []
    ruins = []
    
    for curso in MAJORS_DATABASE:
        score = 0
        
        # 1. Pontuação baseada nos Interesses (RIASEC)
        matches = sum(1 for letter in top_interesses if letter in curso["riasec"])
        if matches == 2:
            score += 60
        elif matches == 1:
            score += 30

        # 2. Pontuação baseada na Personalidade (Big Five)
        distancia_total = 0
        if bigfive_perc:
            for trait, valor_ideal in curso["bigfive"].items():
                valor_usuario = bigfive_perc.get(trait, 50)
                distancia_total += abs(valor_ideal - valor_usuario)
            score += max(0, 40 - (distancia_total / 5)) 

        # 3. Lógica do ENEM
        diff = nota_enem - curso["corte_medio"]
        if diff > 50:
            status = "Fácil entrar e manter (você está bem acima da média)"
            color = "text-emerald-400"
        elif diff > -20:
            status = "Possível, mas concorrência alta (perto da média)"
            color = "text-amber-400"
        else:
            status = "Difícil entrar e provavelmente desafiador se manter (abaixo da média)"
            color = "text-red-400"

        curso_info = {
            "name": curso["name"],
            "status": status,
            "color": color,
            "diff": diff,
            "corte": curso["corte_medio"],
            "dificuldade": curso.get("dificuldade", "Média"),
            "match_score": round(score, 1)
        }

        # Threshold de aprovação
        if score >= 50: 
            recomendados.append(curso_info)
        else:
            ruins.append(curso_info)

    return sorted(recomendados, key=lambda x: x["diff"], reverse=True), ruins

# ====================== ROTAS ======================
@app.route("/")
def home():
    completed = session.get("completed_tests", [])
    return render_template("index.html", completed=completed, progress=len(completed))

@app.route("/bigfive", methods=["GET", "POST"])
def bigfive():
    if request.method == "POST":
        answers = [request.form.get(f"q{i}") for i in range(len(QUESTIONS))]
        if None in answers:
            flash("Responda todas as perguntas", "danger")
            return redirect(url_for("bigfive"))
            
        try:
            raw, perc = calculate_bigfive(answers)
            session["bigfive"] = {"raw": raw, "perc": perc}
            completed = session.get("completed_tests", [])
            if "bigfive" not in completed:
                completed.append("bigfive")
                session["completed_tests"] = completed
            flash("Big Five concluído!", "success")
            return redirect(url_for("home"))
        except Exception as e:
            flash("Ocorreu um erro ao processar o teste.", "danger")
            
    return render_template("bigfive.html", questions=enumerate(QUESTIONS))

@app.route("/interesses", methods=["GET", "POST"])
def interesses():
    if request.method == "POST":
        answers = [request.form.get(f"q{i}") for i in range(len(INTEREST_QUESTIONS))]
        if None in answers:
            flash("Responda todas!", "danger")
        else:
            raw, top2 = calculate_interests(answers)
            session["interests"] = {"raw": raw, "top2": top2}
            completed = session.get("completed_tests", [])
            if "interesses" not in completed:
                completed.append("interesses")
                session["completed_tests"] = completed
            flash("Interesses concluídos!", "success")
            return redirect(url_for("home"))
    return render_template("interesses.html", questions=enumerate(INTEREST_QUESTIONS))

@app.route("/enem", methods=["GET", "POST"])
def enem():
    if request.method == "POST":
        try:
            nota_enem = float(request.form.get("nota_enem"))
            if 0 <= nota_enem <= 1000:
                session["enem"] = nota_enem
                completed = session.get("completed_tests", [])
                if "enem" not in completed:
                    completed.append("enem")
                    session["completed_tests"] = completed
                flash(f"Nota ENEM {nota_enem} registrada!", "success")
                return redirect(url_for("home"))
            else:
                flash("Nota deve ser entre 0 e 1000", "danger")
        except ValueError:
            flash("Digite um número válido", "danger")
    return render_template("enem.html")

@app.route("/final")
def final():
    if len(session.get("completed_tests", [])) < 3:
        flash("Complete os 3 testes primeiro!", "warning")
        return redirect(url_for("home"))
    
    bf = session.get("bigfive", {}).get("perc", {"E":50,"A":50,"C":50,"N":50,"O":50})
    top2 = session.get("interests", {}).get("top2", "IA")
    nota_enem = session.get("enem", 0)
    
    top_jobs, bad_fits = recomendar_cursos(bf, top2, nota_enem)
    
    return render_template("final.html", 
                           top_jobs=top_jobs, 
                           bad_fits=bad_fits,
                           bigfive=bf)
    
if __name__ == "__main__":
    app.run(debug=True)
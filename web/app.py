from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('./index.html')

@app.route('/index')
def index_web():
    return render_template('./index.html')

@app.route('/tareas')
def doing():
    return render_template('./tareas.html')

@app.route('/calendar')
def calendario():
    return render_template('./calendar.html')

if __name__ == '__main__':
    app.run(debug=True)
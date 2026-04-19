import sys
import os

# Aggiunge la cartella corrente al percorso di ricerca di Python
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.app import create_app

app = create_app()

if __name__ == '__main__':
    port  = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV', 'development') != 'production'
    app.run(debug=debug, host='0.0.0.0', port=port)
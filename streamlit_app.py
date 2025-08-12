# streamlit_app.py (na RAIZ do repositório)
import os
import sys

# adiciona a pasta 'oraculo' ao PYTHONPATH
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "oraculo"))

# importa seu app (seu código já executa ao importar)
import app  # noqa: F401

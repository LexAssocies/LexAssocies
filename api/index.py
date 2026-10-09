"""Point d'entrée Vercel pour les routes API LEX ASSOCIÉS."""
from server import initialize, App

initialize()

class handler(App):
    """Gestionnaire HTTP explicite détecté par le runtime Vercel."""
    pass

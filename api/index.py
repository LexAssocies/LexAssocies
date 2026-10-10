"""Point d'entrée Vercel pour les routes API LEX ASSOCIÉS."""
from server import initialize, App
from urllib.parse import urlparse, parse_qs

initialize()

class handler(App):
    """Gestionnaire HTTP explicite détecté par le runtime Vercel."""
    def _restore_path(self):
        parsed=urlparse(self.path); target=parse_qs(parsed.query).get('__path',[None])[0]
        if target and target.startswith('/api/') and not target.startswith('/api/index.py'):
            self.path=target
    def do_GET(self):
        self._restore_path(); return super().do_GET()
    def do_POST(self):
        self._restore_path(); return super().do_POST()
